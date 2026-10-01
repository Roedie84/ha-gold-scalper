"""Datasets: onveranderlijke snapshots van marktdata, met een canonieke hash.

Het barsarchief is muteerbaar - ``store()`` doet ``INSERT OR REPLACE``, en
reparaties maken daar gebruik van. Een experiment dat naar het archief
verwijst, is dus niet reproduceerbaar. Een experiment verwijst daarom naar een
**snapshot**: een kopie met een hash die vastlegt wat er precies in zat.

Deze module ontvangt uitsluitend gewone gegevens (``BarInput``,
``MarketWindow``, ``DatasetSpec``). Ze kent het barsarchief niet en krijgt het
nooit in handen; een brug buiten het Lab (``lab_bridge``) leest het archief
alleen-lezend uit en levert deze gegevens aan.

Canonieke hash, versie 1
------------------------

Tekst in UTF-8, regels gescheiden door ``\\n``, met een afsluitende ``\\n``.
SHA-256 over die bytes, als kleine hexadecimale letters.

Koptekst::

    GSLAB-DATASET|<hash_version>|<symbol>|<timeframe>|<timezone>|<precision>|<bar_count>

Per bar, oplopend op tijdstip::

    <ts>|<open>|<high>|<low>|<close>|<volume>|<source>|<bar_status>

* ``ts``: gehele seconden sinds 1970-01-01 in UTC, decimaal, zonder voorloopnullen.
* prijzen: decimaal met punt als scheidingsteken en precies ``precision``
  cijfers achter de punt, ontstaan uit ``Decimal(repr(float))`` afgerond met
  ROUND_HALF_EVEN. ``repr`` van een float is op elk platform de kortste
  weergave die exact terugleest.
* ``volume``: zes cijfers achter de punt, zelfde afronding; ontbrekend als ``-``.
* ``source`` en ``bar_status``: de tekst zelf; ``|`` en regeleindes zijn
  daarin niet toegestaan.

Twee datasets met dezelfde OHLC maar een ander symbool, tijdsframe, bron,
barstatus of volume krijgen dus een andere identiteit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from math import isfinite

from ..strategy.aggregator import BAR_SECONDS

HASH_VERSION = 1

#: Toegestane barstatussen. ``incomplete`` komt van de brug: de laatste bar
#: die op het moment van uitlezen nog liep.
BAR_STATUSES = ("closed", "incomplete", "unknown")

OK, WARNING, BLOCKED, INFO = "OK", "WARNING", "BLOCKED", "INFO"
_RANG = {INFO: 0, OK: 0, WARNING: 1, BLOCKED: 2}

#: Hoeveel voorbeelden een bevinding meeneemt; de telling is altijd volledig.
MAX_VOORBEELDEN = 5


class DatasetError(ValueError):
    """Invoer waarmee geen snapshot gemaakt kan worden."""


# --------------------------------------------------------------------------- #
# invoer
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class BarInput:
    """Eén bar, zoals de brug hem aanlevert. Alleen gewone waarden."""

    ts: int | datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source: str
    bar_status: str = "unknown"


@dataclass(frozen=True, slots=True)
class MarketWindow:
    """Een venster waarin de markt volgens het rooster open is, in UTC."""

    start_ts: int
    end_ts: int


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    symbol: str
    timeframe: str
    instrument_precision: int
    #: ``instrument_metadata`` of ``fallback``.
    precision_origin: str = "fallback"
    #: Waar de gegevens vandaan komen, bijvoorbeeld ``bar_archive``.
    source: str = ""
    timezone: str = "UTC"


@dataclass(slots=True)
class Finding:
    code: str
    severity: str
    count: int
    detail: str
    examples: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "count": self.count,
                "detail": self.detail, "examples": self.examples}


@dataclass(slots=True)
class CanonicalBar:
    ts: int
    open: str
    high: str
    low: str
    close: str
    volume: str | None
    source: str
    bar_status: str

    def line(self) -> str:
        return "|".join((
            str(self.ts), self.open, self.high, self.low, self.close,
            self.volume if self.volume is not None else "-",
            self.source, self.bar_status,
        ))


@dataclass(slots=True)
class PreparedDataset:
    """Klaar om op te slaan: canonieke bars, hash en kwaliteit."""

    spec: DatasetSpec
    bars: list[CanonicalBar]
    hash: str
    quality_status: str
    findings: list[Finding]

    @property
    def start_ts(self) -> int:
        return self.bars[0].ts

    @property
    def end_ts(self) -> int:
        return self.bars[-1].ts


# --------------------------------------------------------------------------- #
# normalisatie
# --------------------------------------------------------------------------- #

def to_utc_seconds(ts: int | datetime) -> int:
    """Tijdstip naar gehele UTC-seconden. Een tijd zonder tijdzone wordt geweigerd."""
    if isinstance(ts, bool):
        raise DatasetError("een tijdstip mag geen bool zijn")
    if isinstance(ts, int):
        return ts
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            raise DatasetError(
                "tijdstip zonder tijdzone geweigerd: niet te weten welk moment bedoeld is"
            )
        return int(ts.astimezone(timezone.utc).timestamp())
    raise DatasetError(f"onbekend tijdstiptype: {type(ts).__name__}")


def canonical_price(waarde: float, precisie: int) -> tuple[str, bool]:
    """Prijs als canonieke tekst, en of er achter de precisie iets verloren ging."""
    try:
        getal = float(waarde)
    except (ValueError, TypeError) as err:
        raise DatasetError(f"geen geldige prijs: {waarde!r}") from err
    if not isfinite(getal):
        # Geen canonieke decimale vorm; de OHLC-controle blokkeert de dataset.
        return repr(getal), False
    exact = Decimal(repr(getal))
    stap = Decimal(1).scaleb(-precisie)
    afgerond = exact.quantize(stap, rounding=ROUND_HALF_EVEN)
    return format(afgerond, "f"), afgerond != exact


def canonical_volume(waarde: float | None) -> str | None:
    if waarde is None:
        return None
    if not isfinite(float(waarde)):
        return repr(float(waarde))
    afgerond = Decimal(repr(float(waarde))).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_EVEN,
    )
    return format(afgerond, "f")


def _schone_tekst(waarde: str, veld: str) -> str:
    tekst = str(waarde)
    if "|" in tekst or "\n" in tekst or "\r" in tekst:
        raise DatasetError(f"{veld} mag geen '|' of regeleinde bevatten: {tekst!r}")
    return tekst


def canonical_text(spec: DatasetSpec, bars: list[CanonicalBar]) -> str:
    kop = "|".join((
        "GSLAB-DATASET", str(HASH_VERSION), _schone_tekst(spec.symbol, "symbol"),
        _schone_tekst(spec.timeframe, "timeframe"),
        _schone_tekst(spec.timezone, "timezone"),
        str(spec.instrument_precision), str(len(bars)),
    ))
    return "\n".join([kop, *(b.line() for b in bars)]) + "\n"


def dataset_hash(spec: DatasetSpec, bars: list[CanonicalBar]) -> str:
    return hashlib.sha256(canonical_text(spec, bars).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# voorbereiden: valideren, normaliseren, kwaliteit, hash
# --------------------------------------------------------------------------- #

def _voorbeeld(lijst: list, waarde) -> None:
    if len(lijst) < MAX_VOORBEELDEN:
        lijst.append(waarde)


def prepare(
    spec: DatasetSpec,
    bars: list[BarInput],
    windows: list[MarketWindow] | None,
    created_at_ts: int,
) -> PreparedDataset:
    """Maak van ruwe invoer een snapshot die klaar is om op te slaan.

    ``windows`` beschrijft wanneer de markt volgens het rooster open is. Is het
    ``None``, dan is de verwachting onbekend: een gat heet dan
    ``unknown_market_expectation``, niet "ontbrekend".
    """
    # --- metadata: zonder deze bestaat er geen dataset --------------------- #
    if not spec.symbol or not spec.timeframe:
        raise DatasetError("symbool en tijdsframe zijn verplicht")
    if spec.timeframe not in BAR_SECONDS:
        raise DatasetError(f"onbekend tijdsframe: {spec.timeframe}")
    if not isinstance(spec.instrument_precision, int) or not 0 <= spec.instrument_precision <= 10:
        raise DatasetError("instrumentprecisie moet een geheel getal van 0 tot 10 zijn")
    if spec.timezone != "UTC":
        raise DatasetError("datasets worden in UTC opgeslagen")
    if not bars:
        raise DatasetError("een dataset zonder bars bestaat niet")

    lengte = BAR_SECONDS[spec.timeframe]
    bevindingen: list[Finding] = []

    # --- normaliseren ------------------------------------------------------- #
    genormaliseerd: list[tuple[int, CanonicalBar, BarInput]] = []
    precisieverlies, precisievoorb = 0, []
    for ruw in bars:
        ts = to_utc_seconds(ruw.ts)
        if ruw.bar_status not in BAR_STATUSES:
            raise DatasetError(f"onbekende barstatus: {ruw.bar_status!r}")
        prijzen = []
        for veld in ("open", "high", "low", "close"):
            tekst, verloren = canonical_price(getattr(ruw, veld), spec.instrument_precision)
            prijzen.append(tekst)
            if verloren:
                precisieverlies += 1
                _voorbeeld(precisievoorb, {"ts": ts, "veld": veld, "waarde": getattr(ruw, veld)})
        genormaliseerd.append((ts, CanonicalBar(
            ts, *prijzen, canonical_volume(ruw.volume),
            _schone_tekst(ruw.source, "source"), ruw.bar_status,
        ), ruw))

    # --- volgorde ----------------------------------------------------------- #
    uit_volgorde = sum(
        1 for a, b in zip(genormaliseerd, genormaliseerd[1:]) if b[0] < a[0]
    )
    if uit_volgorde:
        bevindingen.append(Finding(
            "out_of_order_input", WARNING, uit_volgorde,
            "De invoer was niet oplopend in tijd; de snapshot is canoniek "
            "gesorteerd. Er is niets weggelaten.",
        ))
    genormaliseerd.sort(key=lambda x: x[0])

    # --- duplicaten --------------------------------------------------------- #
    uniek: list[tuple[int, CanonicalBar, BarInput]] = []
    gelijk, strijdig, strijdvoorb = 0, 0, []
    for item in genormaliseerd:
        if uniek and uniek[-1][0] == item[0]:
            if uniek[-1][1].line() == item[1].line():
                gelijk += 1
            else:
                strijdig += 1
                _voorbeeld(strijdvoorb, item[0])
            continue
        uniek.append(item)
    if gelijk:
        bevindingen.append(Finding(
            "exact_duplicate", WARNING, gelijk,
            "Identieke bar meermaals aangeleverd; één exemplaar bewaard.",
        ))
    if strijdig:
        bevindingen.append(Finding(
            "conflicting_duplicate", BLOCKED, strijdig,
            "Hetzelfde tijdstip met verschillende waarden. Welke juist is, valt "
            "niet deterministisch te bepalen.", strijdvoorb,
        ))

    # --- OHLC en volume ----------------------------------------------------- #
    fout_ohlc, ohlcvoorb, fout_vol, volvoorb, vlak = 0, [], 0, [], 0
    for ts, cb, ruw in uniek:
        waarden = (ruw.open, ruw.high, ruw.low, ruw.close)
        ongeldig = (
            not all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in waarden)
            or not (ruw.low <= ruw.open <= ruw.high)
            or not (ruw.low <= ruw.close <= ruw.high)
            or not (ruw.low <= ruw.high)
        )
        if ongeldig:
            fout_ohlc += 1
            _voorbeeld(ohlcvoorb, ts)
        elif ruw.open == ruw.high == ruw.low == ruw.close:
            vlak += 1
        if ruw.volume is not None and (not isfinite(ruw.volume) or ruw.volume < 0):
            fout_vol += 1
            _voorbeeld(volvoorb, ts)
    if fout_ohlc:
        bevindingen.append(Finding(
            "invalid_ohlc", BLOCKED, fout_ohlc,
            "Laag, open, slot en hoog voldoen niet aan laag <= open,slot <= hoog, "
            "of een prijs is niet positief en eindig.", ohlcvoorb,
        ))
    if fout_vol:
        bevindingen.append(Finding(
            "invalid_volume", WARNING, fout_vol,
            "Negatief of niet-eindig volume. De strategie gebruikt geen volume; "
            "daarom een waarschuwing en geen blokkade.", volvoorb,
        ))
    if vlak:
        bevindingen.append(Finding(
            "flat_bar", INFO, vlak,
            "Open, hoog, laag en slot gelijk. Op zichzelf geen bewijs van een "
            "onvolledige bar; niet verwijderd.",
        ))

    # --- raster ------------------------------------------------------------- #
    naast = [ts for ts, *_ in uniek if ts % lengte]
    if naast:
        bevindingen.append(Finding(
            "off_grid", WARNING, len(naast),
            f"Tijdstip valt niet op het {spec.timeframe}-raster.", naast[:MAX_VOORBEELDEN],
        ))

    # --- bron --------------------------------------------------------------- #
    bronnen = sorted({cb.source for _, cb, _ in uniek})
    if len(bronnen) > 1:
        per_bron = {b: sum(1 for _, cb, _ in uniek if cb.source == b) for b in bronnen}
        bevindingen.append(Finding(
            "mixed_source", WARNING, len(bronnen),
            "Bars uit meer dan één bron in één dataset.", [per_bron],
        ))

    # --- onvolledige laatste bar -------------------------------------------- #
    laatste_ts, laatste_cb, _ = uniek[-1]
    if laatste_cb.bar_status == "incomplete" or laatste_ts + lengte > created_at_ts:
        bevindingen.append(Finding(
            "incomplete_last_bar", WARNING, 1,
            "De laatste bar liep nog op het moment van de snapshot (status of "
            "tijd). Hij is niet verwijderd; zijn status staat in de identiteit.",
            [laatste_ts],
        ))

    # --- gaten ten opzichte van de verwachting ------------------------------ #
    gaten = [
        t for (a, *_), (b, *_) in zip(uniek, uniek[1:])
        for t in range(a + lengte, b, lengte)
    ]
    if gaten:
        if windows is None:
            bevindingen.append(Finding(
                "unknown_market_expectation", INFO, len(gaten),
                "Er ontbreken tijdstippen, maar zonder rooster is niet te zeggen of "
                "de markt toen open was. Niet als ontbrekend geteld.",
                gaten[:MAX_VOORBEELDEN],
            ))
        else:
            def open_op(t: int) -> bool:
                return any(w.start_ts <= t < w.end_ts for w in windows)
            ontbreekt = [t for t in gaten if open_op(t)]
            dicht = len(gaten) - len(ontbreekt)
            if ontbreekt:
                bevindingen.append(Finding(
                    "missing_during_expected_market_hours", WARNING, len(ontbreekt),
                    "Tijdstippen zonder bar terwijl de markt volgens het rooster open was.",
                    ontbreekt[:MAX_VOORBEELDEN],
                ))
            if dicht:
                bevindingen.append(Finding(
                    "expected_market_closure", INFO, dicht,
                    "Tijdstippen zonder bar terwijl de markt volgens het rooster dicht was.",
                ))
    if windows is not None:
        onverwacht = [
            ts for ts, *_ in uniek
            if not any(w.start_ts <= ts < w.end_ts for w in windows)
        ]
        if onverwacht:
            bevindingen.append(Finding(
                "unexpected_bar", WARNING, len(onverwacht),
                "Bar op een moment dat de markt volgens het rooster dicht was.",
                onverwacht[:MAX_VOORBEELDEN],
            ))

    # --- precisie ----------------------------------------------------------- #
    if precisieverlies:
        bevindingen.append(Finding(
            "precision_loss", WARNING, precisieverlies,
            f"Waarden met meer dan {spec.instrument_precision} decimalen; afgerond "
            "met ROUND_HALF_EVEN.", precisievoorb,
        ))
    if spec.precision_origin != "instrument_metadata":
        bevindingen.append(Finding(
            "precision_fallback", INFO, 1,
            f"Precisie {spec.instrument_precision} komt niet uit instrumentmetadata "
            f"maar uit '{spec.precision_origin}'.",
        ))

    canoniek = [cb for _, cb, _ in uniek]
    zwaarste = max((_RANG[f.severity] for f in bevindingen), default=0)
    status = {0: OK, 1: WARNING, 2: BLOCKED}[zwaarste]
    return PreparedDataset(spec, canoniek, dataset_hash(spec, canoniek), status, bevindingen)
