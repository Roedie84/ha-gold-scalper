// Gold Scalper Lab - fase 9A paneeltoets.
//
// Alleen lezen. Geen knoppen, geen acties, geen externe bronnen.
// Authenticatie loopt via hass.callApi: de frontend van Home Assistant voegt
// zelf de sessie toe. Deze module slaat geen token op en zet er geen in een URL.
// Alle weergegeven waarden gaan via textContent.

const STATUS_PATH = "gold_scalper/lab/status";
const ELEMENT_NAME = "gold-scalper-lab-panel";
const EXPECTED_API_VERSION = 1;

const STYLE = `
:host {
  display: block;
  min-height: 100%;
  background: var(--primary-background-color);
  color: var(--primary-text-color);
  font-family: var(--ha-font-family-body, Roboto, "Noto Sans", sans-serif);
}
.bar {
  display: flex;
  align-items: center;
  gap: 4px;
  height: var(--header-height, 56px);
  padding: 0 12px;
  background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, var(--text-primary-color, #fff));
  font-size: 20px;
}
main {
  max-width: 560px;
  margin: 0 auto;
  padding: 32px 20px 48px;
}
h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
h2 {
  margin: 4px 0 28px;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.12em;
  color: var(--secondary-text-color);
}
dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 10px 24px;
  margin: 0;
  padding: 20px 0 0;
  border-top: 1px solid var(--divider-color);
  font-size: 15px;
}
dt { color: var(--secondary-text-color); }
dd { margin: 0; font-variant-numeric: tabular-nums; }
dd.ok { color: var(--success-color, #2e7d32); }
dd.bad { color: var(--error-color, #c62828); }
p.note {
  margin: 28px 0 0;
  font-size: 13px;
  color: var(--secondary-text-color);
}
`;

const ERROR_TEXT = {
  open_failed: "fout: database niet te openen",
  recovery_failed: "fout: herstel mislukt",
  read_failed: "fout: database niet te lezen",
  not_loaded: "fout: Lab niet geladen",
};

class GoldScalperLabPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._requested = false;
    this._root = this.attachShadow({ mode: "open" });
    this._build();
  }

  set hass(hass) {
    this._hass = hass;
    this._menu.hass = hass;
    if (!this._requested) {
      this._requested = true;
      this._load();
    }
  }

  set narrow(value) {
    this._menu.narrow = value;
  }

  set panel(_value) {
    // Geen paneelconfiguratie in 9A.
  }

  _el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  _build() {
    const style = this._el("style", STYLE);
    const bar = this._el("div", undefined, "bar");
    this._menu = document.createElement("ha-menu-button");
    bar.appendChild(this._menu);
    bar.appendChild(this._el("span", "Gold Scalper Lab"));

    const main = this._el("main");
    main.appendChild(this._el("h1", "GOLD SCALPER LAB"));
    main.appendChild(this._el("h2", "FASE 9A PANEL SPIKE"));
    this._list = this._el("dl");
    this._row("Status", "laden…");
    main.appendChild(this._list);
    main.appendChild(this._el("p",
      "Alleen lezen. Dit paneel start niets en wijzigt niets.", "note"));

    this._root.appendChild(style);
    this._root.appendChild(bar);
    this._root.appendChild(main);
  }

  _clear() {
    while (this._list.firstChild) this._list.removeChild(this._list.firstChild);
  }

  _row(label, value, tone) {
    this._list.appendChild(this._el("dt", label));
    this._list.appendChild(this._el("dd", String(value), tone));
  }

  async _load() {
    try {
      const data = await this._hass.callApi("GET", STATUS_PATH);
      this._render(data);
    } catch (err) {
      this._clear();
      const code = err && typeof err.status_code === "number" ? ` (HTTP ${err.status_code})` : "";
      this._row("Backend", `niet bereikbaar${code}`, "bad");
    }
  }

  _render(d) {
    this._clear();
    if (!d || d.api_version !== EXPECTED_API_VERSION) {
      this._row("API-versie", d ? String(d.api_version) : "onbekend", "bad");
      this._row("Let op", "onverwachte API-versie; ververs de pagina", "bad");
      return;
    }
    this._row("Authenticatie", d.authenticated === true ? "actief" : "onbekend",
      d.authenticated === true ? "ok" : "bad");
    this._row("Backend", d.backend === "reachable" ? "bereikbaar" : "onbekend",
      d.backend === "reachable" ? "ok" : "bad");
    this._row("API-versie", d.api_version);
    this._row("Lab-database",
      d.lab_available === true ? "beschikbaar" : (ERROR_TEXT[d.lab_error] || "fout"),
      d.lab_available === true ? "ok" : "bad");
    this._row("Gold Scalper-versie", d.gold_scalper_version);
    const schema = d.lab_schema_version === null
      ? `onbekend (verwacht ${d.lab_schema_expected})`
      : `${d.lab_schema_version} (verwacht ${d.lab_schema_expected})`;
    this._row("Lab-schema", schema,
      d.lab_schema_version === d.lab_schema_expected ? "ok" : "bad");
    this._row("Herstel bij opstart", d.recovery_performed === true
      ? `uitgevoerd, ${d.recovery_interrupted} onderbroken`
      : "niet uitgevoerd");
    this._row("Experimenten", d.experiment_count === null ? "onbekend" : d.experiment_count);
    this._row("Invariant", d.invariant);
  }
}

if (!customElements.get(ELEMENT_NAME)) {
  customElements.define(ELEMENT_NAME, GoldScalperLabPanel);
}
