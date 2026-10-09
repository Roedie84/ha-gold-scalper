// Gold Scalper - broker-dashboard (1.8.0, live koers 1.8.1).
//
// Alleen weergave. Dit paneel plaatst, sluit of wijzigt niets: er zijn geen
// handelsknoppen. Het doet een GET op /api/gold_scalper/broker via
// hass.callApi (de frontend voegt zelf de sessie toe; hier wordt geen token
// bewaard of in een URL gezet) en abonneert zich, als dat kan, op de live
// koers via de bestaande websocket van Home Assistant
// (gold_scalper/broker_stream). Live bedragen zijn indicatief; het officiële
// bedrag komt per cyclus van de broker.
// Geen externe bronnen: geen CDN, geen bibliotheek, geen webfont. De grafiek
// is zelf getekend op een canvas, de equitycurve in SVG.
// Alle tekst van de server gaat door esc() voordat hij in de pagina komt.

const DATA_PATH = "gold_scalper/broker";
const ELEMENT_NAME = "gold-scalper-broker-panel";
const EXPECTED_API = 1;
const POLL_MS = 5000;
const STREAM_TYPE = "gold_scalper/broker_stream";
const HERABONNEER_MS = 30000;
const REPORT_URL = "/api/gold_scalper/report";
const OVERVIEW_URL = "/api/gold_scalper/overview";

const KLEUR = {
  tekst: "#eef3f6", tekst2: "#a9b8c3", tekst3: "#6f8394",
  raster: "rgba(160, 200, 220, 0.07)", as: "rgba(160, 200, 220, 0.16)",
  op: "#2fc28b", neer: "#f05d6c", goud: "#f5c94a", goud2: "#f0b429",
  long: "#5dade2", short: "#fb923c", sl: "#fb6476", tp: "#34d399",
  kruis: "rgba(238, 243, 246, 0.35)", tagbg: "#0b151d",
};

const MERK_SVG = `<svg viewBox="0 0 256 256" aria-hidden="true"><defs>
<linearGradient id="gsb-bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1f3a4a"/><stop offset="1" stop-color="#0d1a24"/></linearGradient>
<linearGradient id="gsb-top" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe9a3"/><stop offset="1" stop-color="#f5c94a"/></linearGradient>
<linearGradient id="gsb-front" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f0b429"/><stop offset="1" stop-color="#b9780f"/></linearGradient></defs>
<rect x="8" y="8" width="240" height="240" rx="52" fill="url(#gsb-bg)"/>
<g stroke="#fff" stroke-opacity=".07" stroke-width="2"><line x1="40" y1="70" x2="216" y2="70"/><line x1="40" y1="110" x2="216" y2="110"/><line x1="40" y1="150" x2="216" y2="150"/></g>
<g stroke-width="3" stroke-linecap="round"><line x1="72" y1="92" x2="72" y2="134" stroke="#e05d5d"/><rect x="64" y="100" width="16" height="24" rx="3" fill="#e05d5d"/>
<line x1="104" y1="74" x2="104" y2="122" stroke="#3ccf8e"/><rect x="96" y="82" width="16" height="30" rx="3" fill="#3ccf8e"/>
<line x1="136" y1="80" x2="136" y2="112" stroke="#e05d5d"/><rect x="128" y="86" width="16" height="18" rx="3" fill="#e05d5d"/>
<line x1="168" y1="48" x2="168" y2="102" stroke="#3ccf8e"/><rect x="160" y="56" width="16" height="36" rx="3" fill="#3ccf8e"/></g>
<polygon points="78,150 178,150 200,196 56,196" fill="url(#gsb-front)"/><polygon points="92,132 164,132 178,150 78,150" fill="url(#gsb-top)"/>
<polygon points="56,196 200,196 196,204 60,204" fill="#7a4c06"/><polygon points="100,138 128,138 122,146 96,146" fill="#fff" opacity=".45"/>
<line x1="84" y1="162" x2="104" y2="162" stroke="#ffe9a3" stroke-width="4" stroke-linecap="round" opacity=".7"/></svg>`;

const IC = {
  grafiek: '<svg class="ic" viewBox="0 0 24 24"><path d="M4 19V5M4 19h16M8 15v-4M12 15V8M16 15v-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  koffer: '<svg class="ic" viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 7V5h6v2" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
  markt: '<svg class="ic" viewBox="0 0 24 24"><path d="M3 12h4l3-7 4 14 3-7h4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  lijst: '<svg class="ic" viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  curve: '<svg class="ic" viewBox="0 0 24 24"><path d="M3 17l5-5 4 3 8-9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  sigma: '<svg class="ic" viewBox="0 0 24 24"><path d="M18 5H6l6 7-6 7h12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  klok: '<svg class="ic" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 7v5l3 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  alarm: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 3l10 18H2L12 3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 10v5M12 18h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  schild: '<svg class="ic" viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
};

const STIJL = `
:host {
  display: block; min-height: 100%;
  --bg0: #050a0f; --bg1: #09131b; --bg2: #0e1c26;
  --paneel: rgba(19, 34, 45, .62); --paneel2: rgba(9, 18, 26, .72);
  --rand: rgba(160, 200, 220, .12); --rand2: rgba(160, 200, 220, .22);
  --tekst: #eef3f6; --tekst2: #a9b8c3; --tekst3: #74879a;
  --goud: #f5c94a; --goud2: #f0b429; --groen: #34d399; --rood: #fb6476;
  --oranje: #fb923c; --blauw: #5dade2; --r: 16px;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  color: var(--tekst); -webkit-font-smoothing: antialiased;
}
* { box-sizing: border-box; }
.root {
  position: relative; isolation: isolate; min-height: 100vh; overflow: hidden;
  background:
    radial-gradient(1000px 560px at 85% -10%, rgba(240, 180, 41, .13), transparent 62%),
    radial-gradient(900px 600px at -8% 22%, rgba(24, 96, 120, .30), transparent 60%),
    radial-gradient(900px 640px at 50% 112%, rgba(18, 70, 92, .32), transparent 62%),
    linear-gradient(180deg, var(--bg0) 0%, var(--bg1) 45%, var(--bg2) 100%);
}
.root::before {
  content: ""; position: absolute; inset: 0; z-index: -1; pointer-events: none;
  background-image: linear-gradient(rgba(160,200,220,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(160,200,220,.035) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(180deg, rgba(0,0,0,.9), transparent 70%);
  -webkit-mask-image: linear-gradient(180deg, rgba(0,0,0,.9), transparent 70%);
}
.wrap { container-type: inline-size; max-width: 1720px; margin: 0 auto; padding: 18px 22px 26px; }
.num, td, .big, .w, .tijd, .px { font-variant-numeric: tabular-nums; font-feature-settings: "tnum"; }
.ic { width: 18px; height: 18px; flex: none; }
.pos { color: var(--groen); } .neg { color: var(--rood); } .dim { color: var(--tekst3); }
small { font-size: .62em; font-weight: 600; color: var(--tekst2); margin-left: 3px; letter-spacing: 0; }
[hidden] { display: none !important; }

/* kop */
.kop { display: flex; align-items: center; gap: 14px 18px; flex-wrap: wrap; padding: 2px 2px 14px; }
.menu { display: none; margin-left: -8px; color: var(--tekst); }
.menu.aan { display: block; }
.merk { display: flex; align-items: center; gap: 12px; min-width: 0; }
.logo { width: 44px; height: 44px; border-radius: 12px; flex: none; box-shadow: 0 6px 22px rgba(240, 180, 41, .28); }
.logo svg { width: 100%; height: 100%; display: block; }
.merknaam { font-size: 19px; font-weight: 800; letter-spacing: .16em; line-height: 1.1; white-space: nowrap; }
.merknaam b { color: var(--goud); font-weight: 800; }
.merksub { font-size: 12px; color: var(--tekst2); letter-spacing: .04em; margin-top: 2px; white-space: nowrap; }
.kop-mid { display: flex; gap: 8px; flex-wrap: wrap; flex: 1 1 0; min-width: 0; }
.kop-r { display: flex; align-items: center; gap: 18px; margin-left: auto; }
.klok { text-align: right; line-height: 1.1; }
.klok .tijd { font-size: 30px; font-weight: 700; letter-spacing: .02em; }
.klok .datum { font-size: 12px; color: var(--tekst2); margin-top: 3px; white-space: nowrap; }
.chip {
  display: inline-flex; align-items: center; gap: 7px; white-space: nowrap;
  font-size: 12px; font-weight: 650; color: var(--tekst2);
  padding: 6px 11px; border-radius: 999px; background: rgba(255,255,255,.045); border: 1px solid var(--rand);
  max-width: 100%; overflow: hidden; text-overflow: ellipsis;
}
.chip b { color: var(--tekst); font-weight: 700; }
.chip.ok { color: var(--groen); border-color: rgba(52, 211, 153, .35); }
.chip.let { color: var(--oranje); border-color: rgba(251, 146, 60, .42); }
.chip.gevaar { color: #fff; background: rgba(251, 100, 118, .22); border-color: rgba(251, 100, 118, .6); }
.chip.neutraal { color: var(--tekst2); }
.chip.demo { color: #1a1204; background: linear-gradient(135deg, #ffe08a, var(--goud2)); border-color: transparent; letter-spacing: .12em; font-weight: 800; box-shadow: 0 4px 16px rgba(240,180,41,.3); }
.chip.echt { color: #fff; background: #d1283e; border-color: transparent; letter-spacing: .12em; font-weight: 800; }
.chip.papier { color: var(--blauw); border-color: rgba(93, 173, 226, .45); letter-spacing: .1em; font-weight: 800; }
.stip { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; background: rgba(255,255,255,.25); }
.stip.ok { background: var(--groen); box-shadow: 0 0 8px rgba(52, 211, 153, .75); }
.stip.let { background: var(--oranje); box-shadow: 0 0 8px rgba(251, 146, 60, .6); }
.stip.gevaar { background: var(--rood); box-shadow: 0 0 8px rgba(251, 100, 118, .75); }
.chip.live { color: var(--groen); border-color: rgba(52, 211, 153, .45); letter-spacing: .1em; font-weight: 800; }
.stip.live { background: var(--groen); box-shadow: 0 0 8px rgba(52, 211, 153, .8); animation: gsb-puls 1.6s ease-in-out infinite; }
@keyframes gsb-puls { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .45; transform: scale(.8); } }
.ind { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: .06em; color: var(--groen); background: rgba(52,211,153,.1); border-radius: 6px; padding: 1px 6px; margin-left: 6px; vertical-align: middle; white-space: nowrap; }
.quote { display: flex; gap: 6px; }
.qv { padding: 6px 12px; border-radius: 12px; background: var(--paneel2); border: 1px solid var(--rand); min-width: 104px; }
.qv .lbl { font-size: 10px; }
.qv .px { font-size: 18px; font-weight: 750; margin-top: 1px; }

/* meldingen */
.meldingen { display: grid; gap: 10px; margin-bottom: 14px; }
.meldingen:empty { display: none; }
.melding { display: flex; align-items: center; gap: 14px; padding: 13px 18px; border-radius: 14px; border: 1px solid var(--rand2); background: var(--paneel); }
.melding .ic { width: 22px; height: 22px; }
.melding b { font-size: 15px; }
.melding span { color: var(--tekst2); font-size: 13px; }
.melding.gevaar { background: linear-gradient(90deg, rgba(251, 100, 118, .34), rgba(251, 100, 118, .1)); border-color: rgba(251, 100, 118, .62); color: #fff; }
.melding.gevaar b { font-size: 17px; letter-spacing: .05em; text-transform: uppercase; }
.melding.gevaar span { color: #ffdbe0; }
.melding.let { border-color: rgba(251, 146, 60, .45); }
.melding.let .ic { color: var(--oranje); }

/* account-strip */
.strip { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 14px; }
.tegel {
  position: relative; overflow: hidden; padding: 13px 15px 13px 17px; border-radius: 14px;
  background: linear-gradient(160deg, rgba(28, 48, 62, .72), rgba(10, 20, 28, .74));
  border: 1px solid var(--rand); box-shadow: 0 10px 30px rgba(0,0,0,.32), inset 0 1px 0 rgba(255,255,255,.05);
  min-width: 0;
}
.tegel::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent, rgba(160,200,220,.25)); box-shadow: 0 0 14px var(--accent, transparent); }
.tegel::after { content: ""; position: absolute; inset: 0; pointer-events: none; background: radial-gradient(120% 90% at 0% 0%, var(--accent-zacht, transparent), transparent 55%); }
.tegel > * { position: relative; z-index: 1; }
.lbl { font-size: 11px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--tekst2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tegel .w { font-size: 23px; font-weight: 800; line-height: 1.15; margin-top: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tegel .s { font-size: 12px; color: var(--tekst2); margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meter { position: relative; height: 6px; border-radius: 99px; background: rgba(255,255,255,.07); overflow: hidden; margin-top: 7px; }
.meter b { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 99px; background: var(--accent, var(--goud)); box-shadow: 0 0 10px var(--accent, transparent); }

/* raster */
.raster { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "grafiek" "positie" "markt" "posities" "equity" "stats" "trades"; }
.paneel {
  min-width: 0; border-radius: var(--r);
  background: linear-gradient(180deg, var(--paneel), var(--paneel2));
  border: 1px solid var(--rand);
  backdrop-filter: blur(16px) saturate(130%); -webkit-backdrop-filter: blur(16px) saturate(130%);
  box-shadow: 0 12px 34px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.05);
  padding: 0 0 16px; display: flex; flex-direction: column;
}
.p-grafiek { grid-area: grafiek; } .p-positie { grid-area: positie; } .p-markt { grid-area: markt; }
.p-posities { grid-area: posities; } .p-equity { grid-area: equity; } .p-stats { grid-area: stats; } .p-trades { grid-area: trades; }
.ph { display: flex; align-items: center; gap: 9px; padding: 14px 16px 10px; color: var(--tekst2); min-width: 0; flex-wrap: wrap; }
.ph h2 { margin: 0; font-size: 12px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; color: var(--tekst); }
.ph .ic { color: var(--goud); }
.ph-r { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; min-width: 0; align-items: center; }
.pb { padding: 0 16px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; }
.leeg { color: var(--tekst3); font-size: 13px; padding: 14px 16px 2px; }

/* grafiek */
.gkop { display: flex; align-items: baseline; gap: 6px 14px; flex-wrap: wrap; padding: 0 16px 8px; }
.gkop .big { font-size: 30px; font-weight: 800; letter-spacing: .01em; }
.gkop .vk { font-size: 14px; font-weight: 700; }
.gkop .ohlc { font-size: 12px; color: var(--tekst2); display: flex; gap: 10px; flex-wrap: wrap; margin-left: auto; }
.gkop .ohlc b { color: var(--tekst); font-weight: 650; }
.wissel { display: inline-flex; padding: 3px; border-radius: 999px; background: var(--paneel2); border: 1px solid var(--rand); }
.wissel button { font: inherit; font-size: 12px; font-weight: 700; color: var(--tekst2); background: none; border: 0; padding: 5px 11px; border-radius: 999px; cursor: pointer; }
.wissel button[aria-pressed="true"] { background: linear-gradient(135deg, #ffe08a, var(--goud2)); color: #1a1204; }
.wissel button:focus-visible { outline: 2px solid var(--goud); outline-offset: 1px; }
.canvasvak { position: relative; margin: 0 12px; height: 470px; flex: 1 1 auto; min-height: 470px; border-radius: 12px; overflow: hidden; background: rgba(4, 10, 15, .55); border: 1px solid var(--rand); touch-action: pan-y; }
.canvasvak canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; cursor: crosshair; }
.glegenda { display: flex; gap: 14px; flex-wrap: wrap; padding: 9px 16px 0; font-size: 11.5px; color: var(--tekst2); }
.glegenda span { display: inline-flex; align-items: center; gap: 6px; }
.glegenda i { display: inline-block; width: 16px; height: 0; border-top: 2px solid; }
.glegenda i.str { border-top-style: dashed; }
.glegenda em { font-style: normal; font-size: 10px; }

/* positie-kaart */
.pk-kop { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.zijde { padding: 4px 10px; border-radius: 8px; font-weight: 800; font-size: 12px; letter-spacing: .12em; }
.zijde.long { background: rgba(93, 173, 226, .16); color: var(--blauw); border: 1px solid rgba(93, 173, 226, .45); }
.zijde.short { background: rgba(251, 146, 60, .14); color: var(--oranje); border: 1px solid rgba(251, 146, 60, .45); }
.pk-pnl { font-size: 34px; font-weight: 800; line-height: 1.05; }
.pk-sub { font-size: 13px; color: var(--tekst2); }
.slt { position: relative; height: 34px; margin-top: 2px; }
.slt .lijn { position: absolute; left: 0; right: 0; top: 15px; height: 4px; border-radius: 4px; background: linear-gradient(90deg, rgba(251,100,118,.55), rgba(160,200,220,.15) 50%, rgba(52,211,153,.55)); }
.slt .mk { position: absolute; top: 9px; width: 2px; height: 16px; background: var(--goud); border-radius: 2px; }
.slt .nu { position: absolute; top: 8px; width: 12px; height: 12px; margin-left: -6px; margin-top: 3px; border-radius: 50%; background: #fff; box-shadow: 0 0 0 3px rgba(255,255,255,.18); }
.slt .e { position: absolute; top: 0; font-size: 10px; color: var(--tekst3); transform: translateX(-50%); white-space: nowrap; }
.slt .e.l { left: 0; transform: none; } .slt .e.r { right: 0; transform: none; }
.kv { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.kv.drie { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.kv > div { padding: 9px 11px; border-radius: 12px; background: rgba(255,255,255,.035); border: 1px solid var(--rand); min-width: 0; }
.kv .lbl { font-size: 10px; letter-spacing: .1em; display: block; }
.kv b { display: block; font-size: 16px; margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
.kv .s { font-size: 11.5px; color: var(--tekst3); margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.aftel { display: grid; gap: 7px; }
.aftel .rij { display: grid; grid-template-columns: 82px minmax(0, 1fr) 62px; gap: 10px; align-items: center; font-size: 12px; color: var(--tekst2); }
.aftel .rij b { text-align: right; color: var(--tekst); font-variant-numeric: tabular-nums; }
.balk { position: relative; height: 6px; border-radius: 99px; background: rgba(255,255,255,.07); overflow: hidden; }
.balk b { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 99px; }
.notitie { font-size: 12.5px; color: var(--tekst2); line-height: 1.5; padding: 10px 12px; border-radius: 12px; background: rgba(255,255,255,.035); border: 1px solid var(--rand); }
.notitie b { color: var(--tekst); }

/* markt */
.bl { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.bl > div { padding: 10px 12px; border-radius: 12px; border: 1px solid var(--rand); background: rgba(255,255,255,.03); min-width: 0; }
.bl .px { font-size: 22px; font-weight: 800; margin-top: 2px; }
.bl .bied .px { color: var(--rood); } .bl .laat .px { color: var(--groen); }
.bereik { position: relative; height: 22px; }
.bereik .lijn { position: absolute; left: 0; right: 0; top: 9px; height: 4px; border-radius: 4px; background: rgba(255,255,255,.08); }
.bereik .vul { position: absolute; top: 9px; height: 4px; border-radius: 4px; background: linear-gradient(90deg, rgba(245,201,74,.25), rgba(245,201,74,.8)); }
.bereik .nu { position: absolute; top: 4px; width: 3px; height: 14px; margin-left: -1px; border-radius: 2px; background: #fff; }
.rijen { display: grid; gap: 0; font-size: 12.5px; }
.rijen div { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,.05); }
.rijen div:last-child { border-bottom: 0; }
.rijen span { color: var(--tekst3); white-space: nowrap; }
.rijen b { font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* tabellen */
.tabel { padding: 0 8px; overflow: hidden; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
th { text-align: left; font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--tekst3); font-weight: 700; padding: 8px 8px; border-bottom: 1px solid var(--rand); white-space: nowrap; }
td { padding: 9px 8px; border-bottom: 1px solid rgba(255,255,255,.045); white-space: nowrap; }
tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: rgba(255,255,255,.025); }
th.r, td.r { text-align: right; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; letter-spacing: .04em; }
.tag.long { color: var(--blauw); background: rgba(93,173,226,.13); }
.tag.short { color: var(--oranje); background: rgba(251,146,60,.13); }
.tag.gemeten { color: var(--groen); background: rgba(52,211,153,.11); }
.tag.berekend { color: var(--goud); background: rgba(245,201,74,.11); }
.tag.aangenomen, .tag.onbekend { color: var(--tekst2); background: rgba(255,255,255,.06); }
.ticket { color: var(--tekst3); font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 11.5px; }

/* equity */
.eqsvg { display: block; width: 100%; height: auto; }
.eqsvg text { font-size: 10.5px; fill: var(--tekst3); font-variant-numeric: tabular-nums; }
.eqvak { padding: 0 12px; }

/* stats */
.oordeel { position: relative; overflow: hidden; padding: 14px 16px 14px 18px; border-radius: 14px; border: 1px solid var(--rand); background: linear-gradient(160deg, rgba(28, 48, 62, .6), rgba(10, 20, 28, .6)); }
.oordeel::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--accent); box-shadow: 0 0 18px var(--accent); }
.oordeel .t { font-size: 22px; font-weight: 800; color: var(--accent); margin-top: 4px; }
.oordeel .s { font-size: 12.5px; color: var(--tekst2); line-height: 1.5; margin-top: 4px; }
.verdeling { display: flex; height: 10px; border-radius: 99px; overflow: hidden; background: rgba(255,255,255,.06); }
.verdeling b { display: block; height: 100%; }
.vlegenda { display: flex; gap: 4px 14px; flex-wrap: wrap; font-size: 12px; color: var(--tekst2); margin-top: 7px; }
.vlegenda i { display: inline-block; width: 9px; height: 9px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }
.tschaal { position: relative; height: 26px; margin-top: 4px; }
.tschaal .lijn { position: absolute; left: 0; right: 0; top: 10px; height: 4px; border-radius: 4px; background: linear-gradient(90deg, rgba(251,100,118,.5), rgba(255,255,255,.08) 40%, rgba(255,255,255,.08) 60%, rgba(52,211,153,.5)); }
.tschaal .dr { position: absolute; top: 7px; width: 1px; height: 10px; background: rgba(255,255,255,.4); }
.tschaal .nu { position: absolute; top: 5px; width: 12px; height: 12px; margin-left: -6px; margin-top: 1px; border-radius: 50%; border: 2px solid #fff; background: var(--accent, var(--goud)); }
.tschaal .e { position: absolute; top: 18px; font-size: 9.5px; color: var(--tekst3); transform: translateX(-50%); }
.checks { display: flex; gap: 6px; flex-wrap: wrap; }

footer { display: flex; gap: 8px 20px; flex-wrap: wrap; justify-content: space-between; color: var(--tekst3); font-size: 12px; padding: 16px 4px 0; }
footer a { color: var(--tekst2); text-decoration: none; border-bottom: 1px dotted var(--tekst3); }
footer a:hover { color: var(--goud); }
footer .demo { color: var(--goud); font-weight: 700; }
.fout { margin: 0 0 14px; }

/* breakpoints op de breedte van het paneel, niet het scherm */
@container (min-width: 720px) {
  .strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .raster { grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-areas: "grafiek grafiek" "positie markt" "posities posities" "equity equity" "stats stats" "trades trades"; }
}
@container (min-width: 1180px) {
  .strip { grid-template-columns: repeat(6, minmax(0, 1fr)); }
  .raster { grid-template-columns: repeat(12, minmax(0, 1fr));
    grid-template-areas:
      "grafiek grafiek grafiek grafiek grafiek grafiek grafiek grafiek positie positie positie positie"
      "grafiek grafiek grafiek grafiek grafiek grafiek grafiek grafiek markt markt markt markt"
      "posities posities posities posities posities posities posities posities posities posities posities posities"
      "equity equity equity equity equity equity equity stats stats stats stats stats"
      "trades trades trades trades trades trades trades stats stats stats stats stats"; }
  .p-stats { align-self: start; }
}
@container (max-width: 719px) {
  .wrap { padding: 12px 12px 22px; }
  .kop { gap: 10px 12px; }
  .klok .tijd { font-size: 24px; }
  .merknaam { font-size: 16px; }
  .kop-r { width: 100%; justify-content: space-between; margin-left: 0; }
  .canvasvak { height: 330px; min-height: 330px; flex: none; margin: 0 8px; }
  .kop-mid { flex: 1 1 100%; order: 3; }
  .merk { flex: 1 1 auto; }
  .trades-t tbody tr:nth-child(n+11) { display: none; }
  .trades-t tbody tr:nth-child(10) { border-bottom: 0; }
  .gkop .big { font-size: 26px; }
  .gkop .ohlc { margin-left: 0; width: 100%; }
  .tegel .w { font-size: 19px; }
  .pk-pnl { font-size: 28px; }
  /* tabellen worden kaarten: geen horizontale scroll */
  table, thead, tbody, tr, td { display: block; width: 100%; }
  thead { display: none; }
  tbody tr { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 12px; padding: 10px 8px; border-bottom: 1px solid var(--rand); }
  tbody tr:last-child { border-bottom: 0; }
  td { border: 0; padding: 3px 0; display: flex; justify-content: space-between; align-items: baseline; gap: 8px; white-space: nowrap; min-width: 0; }
  td > span.v { overflow: hidden; text-overflow: ellipsis; min-width: 0; text-align: right; }
  td.r { text-align: right; }
  td::before { content: attr(data-l); color: var(--tekst3); font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; }
  td.breed { grid-column: 1 / -1; }
}
@container (max-width: 420px) {
  .quote .qv { min-width: 0; padding: 5px 9px; }
  .qv .px { font-size: 15px; }
  .kv.drie { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.p-positie .kv.drie { grid-template-columns: repeat(3, minmax(0, 1fr)); }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
`;

// ----------------------------------------------------------- helpers -- //

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isNum = (v) => typeof v === "number" && isFinite(v);
const MIN = "−";
const nf = {};
function fmt(v, d = 2) {
  if (!isNum(v)) return "—";
  const k = d;
  if (!nf[k]) nf[k] = new Intl.NumberFormat("nl-NL", { minimumFractionDigits: d, maximumFractionDigits: d });
  return nf[k].format(v).replace("-", MIN);
}
function fmtS(v, d = 2) {
  if (!isNum(v)) return "—";
  const s = fmt(Math.abs(v), d);
  if (Math.abs(v) < Math.pow(10, -d) / 2) return s;
  return (v > 0 ? "+" : MIN) + s;
}
const toon = (v) => (!isNum(v) || v === 0 ? "" : v > 0 ? "pos" : "neg");
function duur(s) {
  if (!isNum(s) || s < 0) return "—";
  s = Math.round(s);
  if (s < 3600) return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  if (s < 86400) return `${Math.floor(s / 3600)} u ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")} m`;
  return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} u`;
}
const cel = (l, html, cls = "", id = "", titel = "") =>
  `<td data-l="${l}"${cls ? ` class="${cls}"` : ""}${titel ? ` title="${esc(titel)}"` : ""}><span class="v"${id ? ` id="${id}"` : ""}>${html}</span></td>`;
const VALUTA = { USD: "$", EUR: "€", GBP: "£" };
const val = (c) => (c ? (VALUTA[c] || c) : "");

function niceStep(range, ticks) {
  const raw = range / Math.max(1, ticks);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}

// ------------------------------------------------------------- paneel -- //

class GoldScalperBrokerPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._data = null;
    this._key = null;
    this._fout = null;
    this._tfMul = 1;
    this._zoom = 8;          // pixels per bar
    this._offset = 0;        // bars vanaf rechts
    this._hover = null;
    this._timer = null;
    this._klok = null;
    // live koers (1.8.1)
    this._live = null;           // laatste tick
    this._liveStatus = "uit";    // uit | verbinden | live | terugval
    this._liveReden = null;
    this._liveCandle = null;     // lopende candle uit de ticks
    this._raf = null;
    this._unsub = null;
    this._subGen = 0;
    this._subBezig = false;
    this._herTimer = null;
    this._streamNiet = false;    // server zei: niet beschikbaar (papier)
    this._actief = false;
    this._root = this.attachShadow({ mode: "open" });
    this._bouw();
  }

  set hass(hass) {
    const eerste = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (eerste) { this._laad(); this._start(); }
  }
  set narrow(v) {
    this._narrow = v;
    if (this._menu) { this._menu.narrow = v; this._menu.classList.toggle("aan", !!v); }
  }
  set panel(_v) { /* geen configuratie */ }

  connectedCallback() { this._start(); }
  disconnectedCallback() { this._stop(); }

  _start() {
    if (!this._hass || this._timer) return;
    this._actief = true;
    this._abonneer();
    this._timer = setInterval(() => { if (!document.hidden) this._laad(); }, POLL_MS);
    this._klok = setInterval(() => this._tik(), 1000);
    if (!this._ro && window.ResizeObserver) {
      this._ro = new ResizeObserver(() => {
        this._teken();
        const eq = this._q("#equity");
        if (this._data && eq && eq.clientWidth !== this._eqBreedte) { this._eqBreedte = eq.clientWidth; this._renderEquity(this._data); }
      });
      this._ro.observe(this._vak);
      this._ro.observe(this._q("#equity"));
    }
  }
  _stop() {
    clearInterval(this._timer); clearInterval(this._klok);
    this._timer = this._klok = null;
    this._actief = false;
    this._streamNiet = false;
    this._afmelden();
    clearTimeout(this._herTimer); this._herTimer = null;
    if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
  }

  // ------------------------------------------------- live koers (1.8.1) -- //
  async _abonneer() {
    if (this._unsub || this._subBezig || this._streamNiet || !this._actief) return;
    const conn = this._hass && this._hass.connection;
    if (!conn || typeof conn.subscribeMessage !== "function") return;
    this._subBezig = true;
    const gen = ++this._subGen;
    try {
      const msg = { type: STREAM_TYPE };
      if (this._data && this._data.entry) msg.entry = this._data.entry;
      const unsub = await conn.subscribeMessage((m) => this._opStroom(m), msg);
      if (gen !== this._subGen || !this._actief) { try { unsub(); } catch (_e) { /* al weg */ } return; }
      this._unsub = unsub;
    } catch (err) {
      this._zetLive("uit", (err && err.message) || null);
      if (err && err.code === "not_supported") this._streamNiet = true;
      else this._planHerabonneer();
    } finally { this._subBezig = false; }
  }
  _afmelden() {
    this._subGen++;
    const u = this._unsub;
    this._unsub = null;
    if (u) { try { const r = u(); if (r && r.catch) r.catch(() => {}); } catch (_e) { /* verbinding al dicht */ } }
    this._live = null; this._liveCandle = null; this._liveStatus = "uit";
  }
  _planHerabonneer() {
    clearTimeout(this._herTimer);
    if (!this._actief) return;
    this._herTimer = setTimeout(() => { this._herTimer = null; this._abonneer(); }, HERABONNEER_MS);
  }
  _opStroom(m) {
    if (!m || !this._actief) return;
    if (m.soort === "status") {
      this._zetLive(m.status, m.reden);
      if (m.status === "uit" && m.reden === "gestopt") { this._afmelden(); this._planHerabonneer(); }
      return;
    }
    if (m.soort === "tick" && isNum(m.bied) && isNum(m.laat) && isNum(m.tijd)) {
      this._live = m;
      if (this._liveStatus !== "live") this._zetLive("live", null);
      this._werkLiveCandleBij(m);
      this._planLive();
    }
  }
  _zetLive(status, reden) {
    const was = this._liveStatus;
    this._liveStatus = status || "uit";
    this._liveReden = reden || null;
    if (this._liveStatus !== "live") { this._live = null; this._liveCandle = null; }
    this._renderLiveStatus();
    if (was !== this._liveStatus) this._planLive();
  }
  _liveActief() { return this._liveStatus === "live" && !!this._live && !!this._data; }
  _werkLiveCandleBij(t) {
    const d = this._data;
    if (!d || !isNum(t.mid)) return;
    const base = d.instrument.tf_s || 60;
    const b = Math.floor(t.tijd / base) * base;
    let lc = this._liveCandle;
    if (!lc || lc.t !== b) {
      const c = d.candles, n = c ? c.t.length : 0;
      if (n && b < c.t[n - 1]) return;   // ouder dan de data: negeren
      lc = { t: b, o: t.mid, h: t.mid, l: t.mid, c: t.mid };
      if (n && c.t[n - 1] === b) { lc.o = c.o[n - 1]; lc.h = c.h[n - 1]; lc.l = c.l[n - 1]; }
      this._liveCandle = lc;
    }
    lc.h = Math.max(lc.h, t.mid); lc.l = Math.min(lc.l, t.mid); lc.c = t.mid;
  }
  _planLive() {
    if (this._raf || !this._actief) return;
    this._raf = requestAnimationFrame(() => { this._raf = null; this._renderLive(); });
  }
  _renderLive() {
    const d = this._eff();
    if (!d) return;
    this._renderQuote(d);
    this._renderStrip(d);
    this._renderPositie(d);
    this._renderMarkt(d);
    this._renderPosities(d);
    this._teken();
  }
  _renderLiveStatus() {
    const el = this._q("#livestatus");
    if (!el) return;
    el.innerHTML = this._liveStatus === "live"
      ? '<span class="chip live" title="Koers live via IG-streaming. Live bedragen zijn indicatief; het officiële bedrag komt per cyclus van de broker."><span class="stip live"></span>LIVE</span>'
      : `<span class="chip neutraal" title="${esc(this._liveStatus === "verbinden" ? "Live koers wordt verbonden…" : this._liveReden || "Live koers niet beschikbaar")}"><span class="stip"></span>elke 5 s</span>`;
  }
  // Gegevens met de live koers erin verwerkt; zonder live: de poll-gegevens.
  _eff() {
    const d = this._data;
    if (!d || !this._liveActief()) return d;
    const t = this._live;
    const k = { ...d.koers, bied: t.bied, laat: t.laat, mid: t.mid, spread: t.spread, tijd: t.tijd,
      leeftijd_s: Math.max(0, Date.now() / 1000 - t.tijd), live: true };
    if (d.koers.dag && isNum(t.mid) && isNum(d.koers.dag.ref) && d.koers.dag.ref) {
      const dag = { ...d.koers.dag };
      dag.verandering = t.mid - dag.ref;
      dag.pct = ((t.mid - dag.ref) / dag.ref) * 100;
      if (isNum(dag.hoog)) dag.hoog = Math.max(dag.hoog, t.mid);
      if (isNum(dag.laag)) dag.laag = Math.min(dag.laag, t.mid);
      k.dag = dag;
    }
    const iv = d.instrument.valuta, av = d.account.valuta, rate = d.instrument.omrekening;
    // Zelfde richting als de backend: accountvaluta per eenheid instrumentvaluta.
    const omzet = av && iv && av !== iv ? (isNum(rate) && rate > 0 ? rate : null) : 1;
    const posities = (d.posities || []).map((p) => {
      const koers = p.richting === "long" ? t.bied : t.laat;
      if (!isNum(koers) || !isNum(p.instap) || !isNum(p.units)) return p;
      const punten = p.richting === "long" ? koers - p.instap : p.instap - koers;
      const pnl = punten * p.units;
      return { ...p, koers, punten, pnl, pnl_account: omzet !== null ? pnl * omzet : null,
        pnl_broker: p.pnl_account, live: true };
    });
    return { ...d, koers: k, posities };
  }

  async _laad() {
    if (this._bezig || !this._hass) return;
    this._bezig = true;
    try {
      const q = this._key ? `?since=${encodeURIComponent(this._key)}` : "";
      const d = await this._hass.callApi("GET", DATA_PATH + q);
      this._fout = null;
      if (d && d.ongewijzigd) { this._laatst = Date.now(); this._tik(); return; }
      if (!d || d.api !== EXPECTED_API) { this._fout = "Onverwacht antwoord van de integratie; ververs de browser na de update."; this._render(); return; }
      this._data = d; this._key = d.sleutel; this._laatst = Date.now();
      this._render();
    } catch (err) {
      const body = err && (err.body || err.error);
      this._fout = body && body.error === "starting" ? "Gold Scalper is aan het opstarten; nog geen meting binnen."
        : body && body.error === "no_entry" ? "Geen actieve Gold Scalper-configuratie gevonden."
        : "Geen verbinding met de integratie. Nieuwe poging over enkele seconden.";
      this._render();
    } finally { this._bezig = false; }
  }

  _q(sel) { return this._root.querySelector(sel); }

  _bouw() {
    this._root.innerHTML = `<style>${STIJL}</style>
<div class="root"><div class="wrap">
  <header class="kop">
    <span class="menu-plek"></span>
    <div class="merk"><div class="logo">${MERK_SVG}</div>
      <div><div class="merknaam">GOLD <b>SCALPER</b></div><div class="merksub" id="merksub">Broker-terminal</div></div></div>
    <div class="kop-mid" id="chips"></div>
    <div class="kop-r"><span id="livestatus"></span><div class="quote" id="quote"></div>
      <div class="klok"><div class="tijd" id="tijd">--:--</div><div class="datum" id="datum">&nbsp;</div></div></div>
  </header>
  <div class="meldingen" id="meldingen"></div>
  <section class="strip" id="strip"></section>
  <section class="raster">
    <div class="paneel p-grafiek">
      <div class="ph">${IC.grafiek}<h2 id="g-titel">Koers</h2><div class="ph-r"><div class="wissel" id="tf"></div></div></div>
      <div class="gkop" id="gkop"></div>
      <div class="canvasvak" id="vak"><canvas id="cv" aria-label="Koersgrafiek met candles, open posities en recente trades" role="img"></canvas></div>
      <div class="glegenda">
        <span><i style="border-color:${KLEUR.long}"></i>instap long</span>
        <span><i style="border-color:${KLEUR.short}"></i>instap short</span>
        <span><i class="str" style="border-color:${KLEUR.sl}"></i>stop-loss</span>
        <span><i class="str" style="border-color:${KLEUR.tp}"></i>take-profit</span>
        <span><em style="color:${KLEUR.long}">▲</em><em style="color:${KLEUR.short}">▼</em> instap · <em style="color:${KLEUR.tp}">●</em><em style="color:${KLEUR.sl}">●</em> uitstap (winst/verlies)</span>
        <span class="dim">scroll = zoom · slepen = schuiven · dubbelklik = terug</span>
      </div>
    </div>
    <div class="paneel p-positie"><div class="ph">${IC.koffer}<h2>Open positie</h2><div class="ph-r" id="pk-r"></div></div><div class="pb" id="positie"></div></div>
    <div class="paneel p-markt"><div class="ph">${IC.markt}<h2>Markt</h2><div class="ph-r" id="m-r"></div></div><div class="pb" id="markt"></div></div>
    <div class="paneel p-posities"><div class="ph">${IC.lijst}<h2>Open posities</h2><div class="ph-r" id="op-r"></div></div><div class="tabel" id="posities"></div></div>
    <div class="paneel p-equity"><div class="ph">${IC.curve}<h2>Equity &amp; drawdown</h2><div class="ph-r" id="eq-r"></div></div><div class="eqvak" id="equity"></div></div>
    <div class="paneel p-stats"><div class="ph">${IC.sigma}<h2>Onderzoek &amp; statistiek</h2><div class="ph-r" id="st-r"></div></div><div class="pb" id="stats"></div></div>
    <div class="paneel p-trades"><div class="ph">${IC.klok}<h2>Recente trades</h2><div class="ph-r" id="tr-r"></div></div><div class="tabel" id="trades"></div></div>
  </section>
  <footer id="voet"></footer>
</div></div>`;
    this._menu = document.createElement("ha-menu-button");
    this._menu.className = "menu";
    this._q(".menu-plek").replaceWith(this._menu);
    this._vak = this._q("#vak");
    this._cv = this._q("#cv");
    this._koppelGrafiek();
    this._q("#tf").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      this._tfMul = Number(b.dataset.m) || 1; this._offset = 0;
      this._renderTf(); this._teken();
    });
  }

  // ------------------------------------------------------------ tijd -- //
  _tz() { return (this._hass && this._hass.config && this._hass.config.time_zone) || undefined; }
  _tf(opts) {
    const key = JSON.stringify(opts);
    this._tfc = this._tfc || {};
    if (!this._tfc[key]) {
      try { this._tfc[key] = new Intl.DateTimeFormat("nl-NL", { ...opts, timeZone: this._tz() }); }
      catch (_e) { this._tfc[key] = new Intl.DateTimeFormat("nl-NL", opts); }
    }
    return this._tfc[key];
  }
  _hm(t) { return isNum(t) ? this._tf({ hour: "2-digit", minute: "2-digit" }).format(new Date(t * 1000)) : "—"; }
  _dhm(t) { return isNum(t) ? this._tf({ day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(t * 1000)).replace(",", "") : "—"; }
  _nu() { return (this._nuOverride || Date.now()) / 1000; }

  _tik() {
    const nu = new Date(this._nu() * 1000);
    this._q("#tijd").textContent = this._tf({ hour: "2-digit", minute: "2-digit" }).format(nu);
    const datum = this._tf({ weekday: "short", day: "numeric", month: "short" }).format(nu);
    const d = this._data;
    const bij = d ? ` · bijgewerkt ${this._tf({ hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(d.gegenereerd * 1000))}` : "";
    this._q("#datum").textContent = datum + bij;
    if (d) { this._renderAftel(); }
  }

  // ----------------------------------------------------------- render -- //
  _render() {
    const d = this._eff();
    const m = this._q("#meldingen");
    if (!d) {
      m.innerHTML = this._fout ? `<div class="melding let">${IC.alarm}<div><b>Nog geen gegevens</b><br><span>${esc(this._fout)}</span></div></div>` : "";
      this._tik();
      return;
    }
    this._renderKop(d);
    this._renderMeldingen(d);
    this._renderStrip(d);
    this._renderTf();
    this._renderGkop(d, null);
    this._renderPositie(d);
    this._renderMarkt(d);
    this._renderPosities(d);
    this._renderEquity(d);
    this._renderStats(d);
    this._renderTrades(d);
    this._renderVoet(d);
    this._renderLiveStatus();
    this._tik();
    this._teken();
  }

  _renderKop(d) {
    const st = d.status, ins = d.instrument;
    this._q("#merksub").textContent = `Broker-terminal · ${ins.symbool}`;
    const geld = st.geld === "echt" ? '<span class="chip echt">ECHT GELD</span>'
      : st.geld === "demo" ? '<span class="chip demo">DEMO</span>'
      : '<span class="chip papier">PAPIER</span>';
    const markt = st.markt_open === false
      ? '<span class="chip neutraal"><span class="stip"></span>Markt dicht</span>'
      : '<span class="chip ok"><span class="stip ok"></span>Markt open</span>';
    const a = d.alarm;
    const alarm = a.noodstop.actief ? '<span class="chip gevaar"><span class="stip gevaar"></span>Noodstop</span>'
      : a.dataprobleem.actief ? '<span class="chip let"><span class="stip let"></span>Dataprobleem</span>' : "";
    const handel = st.handel_aan ? '<span class="chip"><span class="stip ok"></span>Handel aan</span>'
      : '<span class="chip neutraal"><span class="stip"></span>Handel uit</span>';
    this._q("#chips").innerHTML =
      `<span class="chip"><b>${esc(ins.naam)}</b>${esc(ins.valuta ? "· " + ins.valuta : "")}</span>` +
      geld + markt +
      `<span class="chip ${esc(st.toon)}"><span class="stip ${esc(st.toon)}"></span>${esc(st.label)}</span>` +
      handel + (st.toestand_label ? `<span class="chip">Toestand <b>${esc(st.toestand_label)}</b></span>` : "") + alarm;
    this._renderQuote(d);
  }

  _renderQuote(d) {
    const k = d.koers;
    this._q("#quote").innerHTML =
      `<div class="qv"><div class="lbl">Bied</div><div class="px">${fmt(k.bied)}</div></div>` +
      `<div class="qv"><div class="lbl">Laat</div><div class="px">${fmt(k.laat)}</div></div>`;
  }

  _renderMeldingen(d) {
    const uit = [];
    const a = d.alarm;
    if (this._fout) uit.push(`<div class="melding let">${IC.alarm}<div><b>Verbinding</b><br><span>${esc(this._fout)}</span></div></div>`);
    if (d.status.geld === "echt") uit.push(`<div class="melding gevaar">${IC.schild}<div><b>Echt geld</b><br><span>Deze bot plaatst orders op een live-account.</span></div></div>`);
    if (a.noodstop.actief) uit.push(`<div class="melding gevaar">${IC.alarm}<div><b>Noodstop</b><br><span>${esc(a.noodstop.reden || "")} · ${esc(d.status.code === "noodstop" ? d.status.detail : "")}</span></div></div>`);
    if (a.afstemming_probleem) uit.push(`<div class="melding gevaar">${IC.alarm}<div><b>Posities kloppen niet</b><br><span>${esc(d.status.detail)}</span></div></div>`);
    if (a.dataprobleem.actief) uit.push(`<div class="melding let">${IC.alarm}<div><b>Dataprobleem</b><br><span>${esc(a.dataprobleem.redenen.join(" · "))}</span></div></div>`);
    this._q("#meldingen").innerHTML = uit.join("");
  }

  _tegel(lbl, w, s, accent, extra = "") {
    const st = accent ? ` style="--accent:${accent};--accent-zacht:${accent}22"` : "";
    return `<div class="tegel"${st}><div class="lbl">${esc(lbl)}</div><div class="w">${w}</div><div class="s">${s}</div>${extra}</div>`;
  }

  _renderStrip(d) {
    const a = d.account, v = val(a.valuta), sv = val(a.stats_valuta);
    const open = (d.posities || []).reduce((s, p) => s + (isNum(p.pnl_account) ? p.pnl_account : isNum(p.pnl) ? p.pnl : 0), 0);
    const kl = (x) => (x > 0 ? "var(--groen)" : x < 0 ? "var(--rood)" : null);
    let vloer = "";
    if (isNum(a.vloer) && isNum(a.equity) && a.equity > 0) {
      const pct = Math.max(0, Math.min(100, (a.vloer_afstand / a.equity) * 100));
      vloer = `<div class="meter"><b style="width:${pct.toFixed(1)}%"></b></div>`;
    }
    this._q("#strip").innerHTML = [
      this._tegel("Equity", `${v}${fmt(a.equity)}`, `saldo ${v}${fmt(a.saldo)}`, "var(--goud)"),
      this._tegel("Open P&L", `<span class="${toon(open)}">${fmtS(open)}</span><small>${esc(a.valuta || "")}</small>`,
        `${(d.posities || []).length} positie(s) open${(d.posities || []).some((p) => p.live) ? ' <span class="ind" title="Berekend uit de live koers; het officiële bedrag komt per cyclus van de broker">live, indicatief</span>' : ""}`, kl(open)),
      this._tegel("Dag-P&L", `<span class="${toon(a.dag_pnl)}">${fmtS(a.dag_pnl)}</span><small>${esc(a.valuta || "")}</small>`, "equity t.o.v. dagstart", kl(a.dag_pnl)),
      this._tegel("Netto run", `<span class="${toon(a.netto)}">${fmtS(a.netto)}</span><small>${esc(a.stats_valuta)}</small>`, `bruto ${fmtS(a.bruto)} · ${d.stats.trades} trades`, kl(a.netto)),
      this._tegel("Kosten", `${sv}${fmt(a.kosten)}`, `${sv}${fmt(a.kosten_per_trade, 2)} per trade`, "var(--oranje)"),
      this._tegel("Vermogensvloer", `${v}${fmt(a.vloer)}`, `afstand ${v}${fmt(a.vloer_afstand)}`, "var(--blauw)", vloer),
    ].join("");
  }

  _tfOpties() {
    const base = (this._data && this._data.instrument.tf_s) || 60;
    const lab = (s) => (s < 3600 ? `${s / 60}m` : `${s / 3600}u`);
    const opts = [1, 5, 15].map((m) => ({ m, s: base * m })).filter((o) => o.s <= 3600);
    if (base >= 300) return [1, 3, 12].map((m) => ({ m, s: base * m, l: lab(base * m) }));
    return opts.map((o) => ({ ...o, l: lab(o.s) }));
  }
  _renderTf() {
    this._q("#tf").innerHTML = this._tfOpties()
      .map((o) => `<button type="button" data-m="${o.m}" aria-pressed="${o.m === this._tfMul}">${o.l}</button>`).join("");
  }

  _renderGkop(d, hov) {
    const k = d.koers, dag = k.dag;
    const vk = dag ? `<span class="vk ${toon(dag.verandering)}">${fmtS(dag.verandering)} (${fmtS(dag.pct, 2)}%)</span>
      <span class="dim" style="font-size:12px">${dag.volledig ? "vandaag" : "sinds " + this._hm(dag.ref_t)}</span>` : "";
    this._q("#g-titel").textContent = `${d.instrument.naam} · ${d.instrument.symbool}`;
    const c = hov || this._laatsteCandle;
    const ohlc = c ? `<span>${esc(this._dhm(c.t))}</span><span>O <b>${fmt(c.o)}</b></span><span>H <b>${fmt(c.h)}</b></span><span>L <b>${fmt(c.l)}</b></span><span>S <b class="${c.c >= c.o ? "pos" : "neg"}">${fmt(c.c)}</b></span>` : "";
    this._q("#gkop").innerHTML = `<span class="big">${fmt(k.mid)}</span>${vk}<div class="ohlc">${ohlc}</div>`;
  }

  _renderPositie(d) {
    const p = (d.posities || [])[0];
    const vl = d.account.valuta;
    const el = this._q("#positie");
    this._q("#pk-r").innerHTML = (d.posities || []).length > 1 ? `<span class="chip">${d.posities.length} open</span>` : "";
    if (!p) {
      const sig = d.status.signaal;
      el.innerHTML = `<div class="notitie"><b>Geen open positie.</b><br>${esc(d.status.detail || "")}</div>` +
        `<div class="kv"><div><span class="lbl">Signaal</span><b>${esc(sig ? sig.richting : "—")}</b><div class="s">score ${fmt(sig && sig.score)}</div></div>` +
        `<div><span class="lbl">Laatste trade</span><b>${d.trades[0] ? `<span class="${toon(d.trades[0].pnl)}">${fmtS(d.trades[0].pnl)}</span>` : "—"}</b><div class="s">${d.trades[0] ? esc(d.trades[0].reden) + " · " + esc(this._hm(d.trades[0].sluit_t)) : ""}</div></div></div>`;
      return;
    }
    const pnl = isNum(p.pnl_account) ? p.pnl_account : p.pnl;
    const pv = isNum(p.pnl_account) ? vl : d.instrument.valuta;
    let slt = "";
    if (isNum(p.sl) && isNum(p.tp) && isNum(p.koers) && p.tp !== p.sl) {
      const lo = Math.min(p.sl, p.tp), hi = Math.max(p.sl, p.tp);
      const pos = (x) => Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100));
      const links = p.richting === "long" ? `SL ${fmt(p.sl)}` : `TP ${fmt(p.tp)}`;
      const rechts = p.richting === "long" ? `TP ${fmt(p.tp)}` : `SL ${fmt(p.sl)}`;
      const lijn = p.richting === "long" ? "" : ' style="transform:scaleX(-1)"';
      slt = `<div class="slt"><div class="lijn"${lijn}></div><span class="e l">${links}</span><span class="e r">${rechts}</span>` +
        `<div class="mk" style="left:${pos(p.instap).toFixed(1)}%"></div><div class="nu" style="left:${pos(p.koers).toFixed(1)}%" title="huidige koers"></div></div>`;
    }
    const afstand = (x) => (isNum(x) && isNum(p.koers) ? fmtS(x - p.koers) : "—");
    el.innerHTML =
      `<div class="pk-kop"><span class="zijde ${p.richting}">${p.richting.toUpperCase()}</span><b class="num">${fmt(p.units)} oz</b><span class="ticket">${esc(p.ticket)}</span></div>` +
      `<div><div class="pk-pnl ${toon(pnl)}">${fmtS(pnl)}<small>${esc(pv || "")}</small>${p.live ? '<span class="ind" title="Berekend uit de live koers; het officiële bedrag komt per cyclus van de broker">live, indicatief</span>' : ""}</div>` +
      (p.live && isNum(p.pnl_broker) ? `<div class="pk-sub">broker (per cyclus): ${fmtS(p.pnl_broker)} ${esc(vl || "")}</div>` : "") +
      `<div class="pk-sub"><span class="${toon(p.punten)}">${fmtS(p.punten, 2)} pt</span> · instap ${fmt(p.instap)} → ${fmt(p.koers)}</div></div>` +
      slt +
      `<div class="kv drie"><div><span class="lbl">Stop-loss</span><b class="neg">${fmt(p.sl)}</b><div class="s">${afstand(p.sl)}</div></div>` +
      `<div><span class="lbl">Take-profit</span><b class="pos">${fmt(p.tp)}</b><div class="s">${afstand(p.tp)}</div></div>` +
      `<div><span class="lbl">Duur</span><b id="pk-duur">${duur(this._nu() - p.geopend)}</b><div class="s">sinds ${esc(this._hm(p.geopend))}</div></div></div>` +
      `<div class="aftel" id="pk-aftel"></div>`;
    this._renderAftel();
  }

  _aftelRijen(p) {
    const verstreken = this._nu() - (p.geopend || this._nu());
    const rij = (lbl, tot, kleur, noot) => {
      if (!isNum(tot) || tot <= 0) return "";
      const rest = tot - verstreken;
      const pct = Math.max(0, Math.min(100, (verstreken / tot) * 100));
      return `<div class="rij" title="${esc(noot)}"><span>${esc(lbl)}</span><div class="balk"><b style="width:${pct.toFixed(1)}%;background:${kleur}"></b></div><b>${rest > 0 ? duur(rest) : "voorbij"}</b></div>`;
    };
    return rij("Tijdstop", p.tijdstop_s, "var(--goud)", `sluit na ${p.tijdstop_s}s als de koers binnen ${p.dode_zone_atr}×ATR van de instap blijft`) +
      rij("Max. duur", p.max_duur_s, "var(--blauw)", "harde bovengrens op de positieduur");
  }

  _renderAftel() {
    const d = this._data;
    if (!d) return;
    const p = (d.posities || [])[0];
    const af = this._q("#pk-aftel");
    if (p && af) {
      af.innerHTML = this._aftelRijen(p);
      const du = this._q("#pk-duur");
      if (du) du.textContent = duur(this._nu() - p.geopend);
    }
    (d.posities || []).forEach((q, i) => {
      const td = this._q(`#op-duur-${i}`);
      if (td) td.textContent = duur(this._nu() - q.geopend);
      const ts = this._q(`#op-uit-${i}`);
      if (ts) ts.textContent = this._uitTekst(q);
    });
  }

  _uitTekst(p) {
    const v = this._nu() - (p.geopend || this._nu());
    const delen = [];
    if (isNum(p.tijdstop_s)) delen.push(v < p.tijdstop_s ? `tijdstop ${duur(p.tijdstop_s - v)}` : "tijdstop actief");
    if (isNum(p.max_duur_s)) delen.push(v < p.max_duur_s ? `max ${duur(p.max_duur_s - v)}` : "max bereikt");
    return delen.join(" · ") || "—";
  }

  _renderMarkt(d) {
    const k = d.koers, dag = k.dag, st = d.status;
    let bereik = "";
    if (dag && isNum(dag.hoog) && isNum(dag.laag) && dag.hoog > dag.laag && isNum(k.mid)) {
      const pos = Math.max(0, Math.min(100, ((k.mid - dag.laag) / (dag.hoog - dag.laag)) * 100));
      bereik = `<div><div class="lbl" style="display:flex;justify-content:space-between"><span>Dagbereik</span><span class="num" style="letter-spacing:0">${fmt(dag.laag)} – ${fmt(dag.hoog)}</span></div>` +
        `<div class="bereik"><div class="lijn"></div><div class="vul" style="left:0;width:${pos.toFixed(1)}%"></div><div class="nu" style="left:${pos.toFixed(1)}%"></div></div></div>`;
    }
    const leeft = isNum(k.leeftijd_s) ? `${fmt(k.leeftijd_s, 1)} s` : "—";
    this._q("#m-r").innerHTML = k.live ? '<span class="chip live"><span class="stip live"></span>live</span>'
      : st.koers_verouderd ? '<span class="chip let">koers verouderd</span>' : `<span class="chip"><span class="stip ok"></span>${esc(leeft)}</span>`;
    const sig = st.signaal;
    this._q("#markt").innerHTML =
      `<div class="bl"><div class="bied"><div class="lbl">Bied</div><div class="px">${fmt(k.bied)}</div></div>` +
      `<div class="laat"><div class="lbl">Laat</div><div class="px">${fmt(k.laat)}</div></div></div>` + bereik +
      `<div class="rijen">` +
      `<div><span>Spread</span><b>${fmt(k.spread, 2)}</b></div>` +
      `<div><span>ATR (${esc(d.instrument.timeframe || "")})</span><b>${fmt(k.atr, 2)}</b></div>` +
      `<div><span>Signaal</span><b>${sig ? `${esc(sig.richting)} · score ${fmt(sig.score)}` : "—"}</b></div>` +
      `<div><span>Waarom geen trade</span><b title="${esc(st.reden_geen_trade || "")}">${esc(st.reden_geen_trade || "—")}</b></div>` +
      `<div><span>Candles</span><b>${d.candles ? d.candles.t.length : 0} × ${esc(d.instrument.timeframe || "")}</b></div>` +
      `</div>`;
  }

  _renderPosities(d) {
    const ps = d.posities || [];
    this._q("#op-r").innerHTML = `<span class="chip">${ps.length}</span>`;
    if (!ps.length) { this._q("#posities").innerHTML = '<div class="leeg">Geen open posities.</div>'; return; }
    const vl = d.account.valuta, iv = d.instrument.valuta;
    const rijen = ps.map((p, i) => {
      const pnl = isNum(p.pnl_account) ? p.pnl_account : p.pnl;
      const pv = isNum(p.pnl_account) ? vl : iv;
      return `<tr>${cel("Ticket", esc(p.ticket), "ticket breed")}` +
        cel("Richting", `<span class="tag ${p.richting}">${p.richting.toUpperCase()}</span>`) +
        cel("Units", fmt(p.units), "r") + cel("Instap", fmt(p.instap), "r") +
        cel("Koers", fmt(p.koers), "r") + cel("SL", fmt(p.sl), "r neg") + cel("TP", fmt(p.tp), "r pos") +
        cel("P&amp;L", `<b>${fmtS(pnl)}</b> <span class="dim">${esc(pv || "")}</span>${p.live ? '<span class="ind" title="live, indicatief">live</span>' : ""}`, `r ${toon(pnl)}`) +
        cel("Punten", fmtS(p.punten), `r ${toon(p.punten)}`) +
        cel("Duur", duur(this._nu() - p.geopend), "r", `op-duur-${i}`) +
        cel("Uitstap", esc(this._uitTekst(p)), "breed", `op-uit-${i}`) + "</tr>";
    }).join("");
    this._q("#posities").innerHTML = `<table><thead><tr><th>Ticket</th><th>Richting</th><th class="r">Units</th><th class="r">Instap</th><th class="r">Koers</th><th class="r">SL</th><th class="r">TP</th><th class="r">P&amp;L</th><th class="r">Punten</th><th class="r">Duur</th><th>Uitstapregime</th></tr></thead><tbody>${rijen}</tbody></table>`;
  }

  _renderEquity(d) {
    const e = d.equity, vak = this._q("#equity");
    const pts = (e.t || []).map((t, i) => ({ t, v: e.equity[i] })).filter((p) => isNum(p.t) && isNum(p.v));
    if (pts.length < 2) { vak.innerHTML = '<div class="leeg">Nog te weinig equitypunten.</div>'; this._q("#eq-r").innerHTML = ""; return; }
    let piek = -Infinity, maxdd = 0;
    const dd = pts.map((p) => { piek = Math.max(piek, p.v); const x = piek > 0 ? ((p.v - piek) / piek) * 100 : 0; maxdd = Math.min(maxdd, x); return x; });
    const W = Math.max(300, Math.round((vak.clientWidth || 784) - 24)), H = W < 520 ? 220 : 250, DH = W < 520 ? 62 : 70, L = 8, R = 62, T = 10, G = 22;
    const t0 = pts[0].t, t1 = pts[pts.length - 1].t || t0 + 1;
    let lo = Math.min(...pts.map((p) => p.v)), hi = Math.max(...pts.map((p) => p.v));
    if (hi - lo < 1) { hi += 0.5; lo -= 0.5; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const x = (t) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - G - DH);
    const ddMin = Math.min(-1, maxdd * 1.15);
    const yd = (v) => H - DH + 16 + (v / ddMin) * (DH - 26);
    const lijn = pts.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    const vlak = `${lijn}L${x(t1).toFixed(1)},${y(lo).toFixed(1)}L${x(t0).toFixed(1)},${y(lo).toFixed(1)}Z`;
    const ddpad = `M${x(t0).toFixed(1)},${yd(0).toFixed(1)}` + pts.map((p, i) => `L${x(p.t).toFixed(1)},${yd(dd[i]).toFixed(1)}`).join("") + `L${x(t1).toFixed(1)},${yd(0).toFixed(1)}Z`;
    const stap = niceStep(hi - lo, 4);
    let grid = "";
    for (let v = Math.ceil(lo / stap) * stap; v <= hi; v += stap) {
      grid += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="${KLEUR.raster}"/><text x="${W - R + 6}" y="${(y(v) + 3.5).toFixed(1)}">${fmt(v, stap < 1 ? 1 : 0)}</text>`;
    }
    const dagen = this._tf({ day: "numeric", month: "short" });
    const tl = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const t = t0 + (t1 - t0) * f;
      const anchor = f === 0 ? "start" : f === 1 ? "end" : "middle";
      return `<text x="${x(t).toFixed(1)}" y="${H - DH - 6}" text-anchor="${anchor}">${esc(dagen.format(new Date(t * 1000)))}</text>`;
    }).join("");
    const last = pts[pts.length - 1];
    const v0 = pts[0].v;
    vak.innerHTML = `<svg class="eqsvg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Equitycurve en drawdown">
<defs><linearGradient id="eqg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${KLEUR.goud}" stop-opacity=".32"/><stop offset="1" stop-color="${KLEUR.goud}" stop-opacity="0"/></linearGradient>
<linearGradient id="ddg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${KLEUR.neer}" stop-opacity=".15"/><stop offset="1" stop-color="${KLEUR.neer}" stop-opacity=".55"/></linearGradient></defs>
${grid}
<line x1="${L}" x2="${W - R}" y1="${y(v0).toFixed(1)}" y2="${y(v0).toFixed(1)}" stroke="rgba(255,255,255,.22)" stroke-dasharray="3 4"/>
<path d="${vlak}" fill="url(#eqg)"/><path d="${lijn}" fill="none" stroke="${KLEUR.goud}" stroke-width="2" stroke-linejoin="round"/>
<circle cx="${x(last.t).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="4" fill="${KLEUR.goud}" stroke="#0b151d" stroke-width="2"/>
${tl}
<line x1="${L}" x2="${W - R}" y1="${yd(0).toFixed(1)}" y2="${yd(0).toFixed(1)}" stroke="${KLEUR.as}"/>
<path d="${ddpad}" fill="url(#ddg)" stroke="${KLEUR.neer}" stroke-width="1"/>
<text x="${W - R + 6}" y="${(yd(0) + 3.5).toFixed(1)}">0%</text><text x="${W - R + 6}" y="${(yd(ddMin) + 3.5).toFixed(1)}">${fmt(ddMin, 1)}%</text>
<text x="${L + 2}" y="${(H - DH + 10).toFixed(1)}" style="font-weight:700;letter-spacing:.1em">DRAWDOWN</text>
</svg>`;
    const vl = val(d.account.valuta);
    const verschil = last.v - v0;
    this._q("#eq-r").innerHTML = `<span class="chip">${vl}${fmt(last.v)} · <span class="${toon(verschil)}">${fmtS(verschil)}</span></span>` +
      `<span class="chip">huidig ${fmt(dd[dd.length - 1], 1)}%</span><span class="chip let">max ${fmt(maxdd, 1)}%</span>`;
  }

  _renderStats(d) {
    const s = d.stats;
    const accent = s.oordeel === "passed" ? "var(--groen)" : s.oordeel === "failed" ? "var(--rood)" : "var(--oranje)";
    this._q("#st-r").innerHTML = s.run ? `<span class="chip">run ${esc(s.run)}</span>` : "";
    const cl = Math.min(100, (s.clusters / Math.max(1, s.clusters_richtgetal)) * 100);
    const tPos = (t) => Math.max(0, Math.min(100, ((t + 4) / 8) * 100));
    const tschaal = isNum(s.t) ? `<div class="tschaal" style="--accent:${s.t >= s.t_drempel ? "var(--groen)" : s.t < 0 ? "var(--rood)" : "var(--goud)"}"><div class="lijn"></div>` +
      `<div class="dr" style="left:${tPos(-s.t_drempel)}%"></div><div class="dr" style="left:${tPos(0)}%"></div><div class="dr" style="left:${tPos(s.t_drempel)}%"></div>` +
      `<span class="e" style="left:${tPos(-s.t_drempel)}%">${MIN}2</span><span class="e" style="left:${tPos(0)}%">0</span><span class="e" style="left:${tPos(s.t_drempel)}%">+2</span>` +
      `<div class="nu" style="left:${tPos(s.t)}%"></div></div>` : "";
    const doel = s.doel_pct || 0, stop = s.stop_pct || 0, onb = s.onbekend_pct || 0;
    const rest = Math.max(0, 100 - doel - stop - onb);
    const lat = s.latency_n ? `${fmt(s.latency_p50, 0)} / ${fmt(s.latency_p99, 0)} ms` : "—";
    const af = s.afstemming;
    const checks = Object.entries(s.poort || {}).map(([k, v]) => `<span class="chip ${v ? "ok" : "neutraal"}">${v ? "✓" : "✗"} ${esc(k.replace(/_/g, " "))}</span>`).join("");
    this._q("#stats").innerHTML =
      `<div class="oordeel" style="--accent:${accent}"><div class="lbl">Oordeel bewijsfase</div><div class="t">${esc(s.oordeel_label || "—")}</div><div class="s">${esc(s.oordeel_tekst || "")}</div></div>` +
      `<div class="kv drie">` +
      `<div><span class="lbl">Trades</span><b>${fmt(s.trades, 0)}</b><div class="s">${fmt(s.winst, 0)} winst · ${fmt(s.verlies, 0)} verlies</div></div>` +
      `<div><span class="lbl">Winst%</span><b>${fmt(s.winst_pct, 1)}%</b><div class="s">trefkans</div></div>` +
      `<div><span class="lbl">Profit factor</span><b class="${isNum(s.pf) ? (s.pf >= 1 ? "pos" : "neg") : ""}">${fmt(s.pf, 2)}</b><div class="s">≥ 1,20 gevraagd</div></div>` +
      `<div><span class="lbl">Netto</span><b class="${toon(s.netto)}">${fmtS(s.netto)}</b><div class="s">${fmtS(s.verwachting)} per trade</div></div>` +
      `<div><span class="lbl">Max. drawdown</span><b>${fmt(s.max_dd_pct, 1)}%</b><div class="s">≤ 25% gevraagd</div></div>` +
      `<div><span class="lbl">Latency p50/${esc(s.latency_staart || "p99")}</span><b>${lat}</b><div class="s">n = ${fmt(s.latency_n, 0)}</div></div>` +
      `</div>` +
      `<div><div class="lbl" style="display:flex;justify-content:space-between"><span>Clusters</span><span class="num" style="letter-spacing:0;color:var(--tekst)">${s.clusters} van ${s.clusters_richtgetal} nodig</span></div>` +
      `<div class="meter" style="--accent:var(--goud)"><b style="width:${cl.toFixed(1)}%"></b></div></div>` +
      `<div><div class="lbl" style="display:flex;justify-content:space-between"><span>t-statistiek (clusters)</span><span class="num ${toon(s.t)}" style="letter-spacing:0">${fmtS(s.t)}</span></div>${tschaal}</div>` +
      `<div><div class="lbl">Hoe trades eindigden${s.exits_noemer ? ` · ${s.exits_noemer}` : ""}</div><div class="verdeling" style="margin-top:7px">` +
      `<b style="width:${doel}%;background:var(--groen)"></b><b style="width:${stop}%;background:var(--rood)"></b><b style="width:${rest}%;background:rgba(160,200,220,.35)"></b><b style="width:${onb}%;background:rgba(255,255,255,.12)"></b></div>` +
      `<div class="vlegenda"><span><i style="background:var(--groen)"></i>doel ${fmt(doel, 0)}%</span><span><i style="background:var(--rood)"></i>stop ${fmt(stop, 0)}%</span><span><i style="background:rgba(160,200,220,.35)"></i>overig ${fmt(rest, 0)}%</span><span><i style="background:rgba(255,255,255,.12)"></i>onbekend ${fmt(onb, 0)}%</span></div></div>` +
      `<div class="rijen"><div><span>Afstemming met broker</span><b class="${af ? (af.in_orde ? "pos" : "neg") : ""}" title="${esc(af ? af.tekst || "" : "")}">${af ? (af.in_orde ? "in orde" : `${af.afwijkingen} afwijking(en)`) : "nog niet"}</b></div></div>` +
      (checks ? `<div><div class="lbl" style="margin-bottom:7px">Live-poort (alleen informatie)</div><div class="checks">${checks}</div></div>` : "");
  }

  _renderTrades(d) {
    const ts = d.trades || [];
    this._q("#tr-r").innerHTML = `<span class="chip">laatste ${ts.length}</span>`;
    if (!ts.length) { this._q("#trades").innerHTML = '<div class="leeg">Nog geen gesloten trades.</div>'; return; }
    const BRON = { measured: "gemeten", calculated: "berekend", assumed: "aangenomen", unknown: "onbekend" };
    const rijen = ts.map((t) => {
      const b = BRON[t.kostenbron] || "onbekend";
      const pa = isNum(t.pnl_account) && t.valuta_account && t.valuta_account !== d.instrument.valuta
        ? ` <span class="dim">(${fmtS(t.pnl_account)} ${esc(t.valuta_account)})</span>` : "";
      return `<tr>${cel("Gesloten", esc(this._dhm(t.sluit_t)), "breed")}` +
        cel("Richting", `<span class="tag ${t.richting}">${t.richting.toUpperCase()}</span>`) +
        cel("Units", fmt(t.units), "r") + cel("Instap", fmt(t.instap), "r") + cel("Uitstap", fmt(t.uitstap), "r") +
        cel("P&amp;L", `<b>${fmtS(t.pnl)}</b>${pa}`, `r ${toon(t.pnl)}`) +
        cel("Reden", esc(t.reden), "", "", t.reden_lang) +
        cel("Kosten", `${fmt(t.kosten)} <span class="tag ${b}">${b}</span>`, "r breed") +
        cel("Duur", duur(t.duur_s), "r") + "</tr>";
    }).join("");
    this._q("#trades").innerHTML = `<table class="trades-t"><thead><tr><th>Gesloten</th><th>Richting</th><th class="r">Units</th><th class="r">Instap</th><th class="r">Uitstap</th><th class="r">P&amp;L ${esc(d.instrument.valuta)}</th><th>Sluitreden</th><th class="r">Kosten · bron</th><th class="r">Duur</th></tr></thead><tbody>${rijen}</tbody></table>`;
  }

  _renderVoet(d) {
    const geld = d.status.geld === "echt" ? '<span class="neg">Live — echt geld</span>'
      : d.status.geld === "demo" ? '<span class="demo">Demo — geen echt geld</span>' : '<span class="demo">Papierhandel — geen echt geld</span>';
    this._q("#voet").innerHTML = `<span>Gold Scalper v${esc(d.versie)} · bronnen: broker (koers, posities, saldo; koers live via IG-streaming als dat beschikbaar is), eigen database (trades, equity) · alleen weergave</span>` +
      `<span>${geld} · <a href="${REPORT_URL}" target="_blank" rel="noopener">Keuringsrapport</a> · <a href="${OVERVIEW_URL}" target="_blank" rel="noopener">Klassiek overzicht</a></span>`;
  }

  // ---------------------------------------------------------- grafiek -- //
  _koppelGrafiek() {
    const cv = this._cv;
    let sleep = null;
    const pos = (e) => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    cv.addEventListener("pointermove", (e) => {
      const p = pos(e);
      if (sleep) {
        const dx = p.x - sleep.x;
        this._offset = Math.max(0, sleep.off + dx / this._zoom);
        this._teken(); return;
      }
      this._hover = p; this._teken();
    });
    cv.addEventListener("pointerleave", () => { this._hover = null; sleep = null; this._teken(); });
    cv.addEventListener("pointerdown", (e) => { if (e.pointerType === "mouse") sleep = { ...pos(e), off: this._offset }; });
    window.addEventListener("pointerup", () => { sleep = null; });
    cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      this._zoom = Math.max(3, Math.min(28, this._zoom * (e.deltaY > 0 ? 0.88 : 1.14)));
      this._teken();
    }, { passive: false });
    cv.addEventListener("dblclick", () => { this._zoom = 8; this._offset = 0; this._teken(); });
  }

  _aggregeer() {
    const d = this._eff();
    const c = d && d.candles;
    if (!c || !c.t.length) return [];
    const base = d.instrument.tf_s || 60;
    const tf = base * this._tfMul;
    const basis = c.t.map((t, i) => ({ t, o: c.o[i], h: c.h[i], l: c.l[i], c: c.c[i] }));
    const laatst = basis[basis.length - 1];
    const lc = this._liveActief() ? this._liveCandle : null;
    if (lc) {
      // 1.8.1: de lopende candle uit de live ticks (high/low/close).
      if (laatst.t === lc.t) { laatst.h = Math.max(laatst.h, lc.h); laatst.l = Math.min(laatst.l, lc.l); laatst.c = lc.c; }
      else if (lc.t > laatst.t) basis.push({ ...lc });
    } else {
      // Laatste koers in de laatste candle verwerken, zoals een broker dat doet.
      const mid = d.koers.mid;
      if (isNum(mid) && d.status.markt_open !== false) { laatst.c = mid; laatst.h = Math.max(laatst.h, mid); laatst.l = Math.min(laatst.l, mid); }
    }
    const uit = [];
    for (const k of basis) {
      const b = Math.floor(k.t / tf) * tf;
      const l = uit[uit.length - 1];
      if (l && l.t === b) { l.h = Math.max(l.h, k.h); l.l = Math.min(l.l, k.l); l.c = k.c; }
      else uit.push({ t: b, o: k.o, h: k.h, l: k.l, c: k.c });
    }
    return uit;
  }

  _teken() {
    const d = this._eff(), cv = this._cv, vak = this._vak;
    if (!cv || !vak) return;
    const W = vak.clientWidth, H = vak.clientHeight;
    if (!W || !H) return;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, W, H);
    const cs = this._aggregeer();
    if (!cs.length) {
      g.fillStyle = KLEUR.tekst3; g.font = "13px system-ui, sans-serif"; g.textAlign = "center";
      g.fillText(d ? "Nog geen candles in het geheugen" : "Laden…", W / 2, H / 2);
      return;
    }
    const AX = W < 520 ? 58 : 70, TB = 24, TOP = 10;
    const pw = W - AX, ph = H - TB - TOP;
    const zoom = W < 520 ? Math.max(3, this._zoom * 0.75) : this._zoom;
    const n = Math.max(10, Math.floor(pw / zoom) - 3);
    const maxOff = Math.max(0, cs.length - n);
    if (this._offset > maxOff) this._offset = maxOff;
    const eind = cs.length - Math.round(this._offset);
    const start = Math.max(0, eind - n);
    const zicht = cs.slice(start, eind);
    const xs = (i) => pw - (zicht.length - i - 0.5) * zoom - 3 * zoom;
    let lo = Math.min(...zicht.map((c) => c.l)), hi = Math.max(...zicht.map((c) => c.h));
    const lijnen = [];
    for (const p of d.posities || []) {
      lijnen.push({ v: p.instap, k: p.richting === "long" ? KLEUR.long : KLEUR.short, t: "entry", p });
      if (isNum(p.sl)) lijnen.push({ v: p.sl, k: KLEUR.sl, t: "sl", p });
      if (isNum(p.tp)) lijnen.push({ v: p.tp, k: KLEUR.tp, t: "tp", p });
    }
    const span0 = Math.max(hi - lo, 0.5);
    for (const l of lijnen) if (isNum(l.v) && l.v > lo - span0 * 1.5 && l.v < hi + span0 * 1.5) { lo = Math.min(lo, l.v); hi = Math.max(hi, l.v); }
    const pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    const y = (v) => TOP + (1 - (v - lo) / (hi - lo)) * ph;
    const font = (s, w = 500) => `${w} ${s}px system-ui, -apple-system, "Segoe UI", sans-serif`;

    // raster + prijsas
    const stap = niceStep(hi - lo, Math.max(3, Math.floor(ph / 60)));
    g.font = font(11); g.textAlign = "left"; g.textBaseline = "middle";
    const tagYs = lijnen.filter((l) => isNum(l.v)).map((l) => y(l.v)).concat(isNum(d.koers.mid) ? [y(d.koers.mid)] : []);
    for (let v = Math.ceil(lo / stap) * stap; v <= hi; v += stap) {
      const yy = Math.round(y(v)) + 0.5;
      g.strokeStyle = KLEUR.raster; g.lineWidth = 1; g.beginPath(); g.moveTo(0, yy); g.lineTo(pw, yy); g.stroke();
      if (tagYs.some((q) => Math.abs(q - yy) < 13)) continue;
      g.fillStyle = KLEUR.tekst3; g.fillText(fmt(v, stap < 1 ? 2 : stap < 10 ? 1 : 0), pw + 8, yy);
    }
    g.strokeStyle = KLEUR.as; g.beginPath(); g.moveTo(pw + 0.5, 0); g.lineTo(pw + 0.5, H); g.moveTo(0, H - TB + 0.5); g.lineTo(W, H - TB + 0.5); g.stroke();

    // tijdas
    const tf = (d.instrument.tf_s || 60) * this._tfMul;
    const elk = Math.max(1, Math.ceil(90 / zoom));
    const stappen = [1, 2, 3, 5, 6, 10, 12, 15, 20, 30, 60, 120, 240];
    const sb = stappen.find((s) => s >= elk) || elk;
    const hmFmt = this._tf({ hour: "2-digit", minute: "2-digit" });
    g.textAlign = "center"; g.textBaseline = "middle";
    zicht.forEach((c, i) => {
      if (Math.floor(c.t / tf) % sb !== 0) return;
      const xx = Math.round(xs(i)) + 0.5;
      if (xx < 22 || xx > pw - 22) return;
      g.strokeStyle = KLEUR.raster; g.beginPath(); g.moveTo(xx, TOP); g.lineTo(xx, H - TB); g.stroke();
      g.fillStyle = KLEUR.tekst3; g.fillText(hmFmt.format(new Date(c.t * 1000)), xx, H - TB / 2);
    });

    // candles
    const bw = Math.max(1, Math.floor(zoom * 0.64));
    zicht.forEach((c, i) => {
      const xx = Math.round(xs(i));
      const op = c.c >= c.o, k = op ? KLEUR.op : KLEUR.neer;
      g.strokeStyle = k; g.fillStyle = k; g.lineWidth = 1;
      g.beginPath(); g.moveTo(xx + 0.5, Math.round(y(c.h))); g.lineTo(xx + 0.5, Math.round(y(c.l))); g.stroke();
      const y1 = Math.round(y(Math.max(c.o, c.c))), y2 = Math.round(y(Math.min(c.o, c.c)));
      g.fillRect(xx - Math.floor(bw / 2), y1, bw, Math.max(1, y2 - y1));
    });

    // markers van recente trades
    const t0 = zicht[0].t, tE = zicht[zicht.length - 1].t + tf;
    const xt = (t) => {
      let i = 0;
      while (i < zicht.length - 1 && zicht[i + 1].t <= t) i++;
      return xs(i);
    };
    for (const m of d.markers || []) {
      const inO = isNum(m.o_t) && m.o_t >= t0 && m.o_t < tE, inS = isNum(m.s_t) && m.s_t >= t0 && m.s_t < tE;
      if (!inO && !inS) continue;
      const win = (m.pnl || 0) >= 0;
      if (inO && inS && isNum(m.instap) && isNum(m.uitstap)) {
        g.strokeStyle = win ? "rgba(52,211,153,.55)" : "rgba(251,100,118,.55)"; g.setLineDash([2, 3]); g.lineWidth = 1;
        g.beginPath(); g.moveTo(xt(m.o_t), y(m.instap)); g.lineTo(xt(m.s_t), y(m.uitstap)); g.stroke(); g.setLineDash([]);
      }
      if (inO && isNum(m.instap)) {
        const xx = xt(m.o_t), yy = y(m.instap), lg = m.richting === "long";
        g.fillStyle = lg ? KLEUR.long : KLEUR.short; g.strokeStyle = "#071017"; g.lineWidth = 1.2;
        g.beginPath();
        if (lg) { g.moveTo(xx, yy + 3); g.lineTo(xx - 5.5, yy + 12); g.lineTo(xx + 5.5, yy + 12); }
        else { g.moveTo(xx, yy - 3); g.lineTo(xx - 5.5, yy - 12); g.lineTo(xx + 5.5, yy - 12); }
        g.closePath(); g.fill(); g.stroke();
      }
      if (inS && isNum(m.uitstap)) {
        g.fillStyle = win ? KLEUR.tp : KLEUR.sl; g.strokeStyle = "#071017"; g.lineWidth = 1.5;
        g.beginPath(); g.arc(xt(m.s_t), y(m.uitstap), 3.6, 0, Math.PI * 2); g.fill(); g.stroke();
      }
    }

    // prijstags op de as
    const tag = (v, kleur, tekst, vul = true) => {
      const yy = Math.max(TOP + 8, Math.min(H - TB - 8, y(v)));
      g.fillStyle = vul ? kleur : KLEUR.tagbg; g.strokeStyle = kleur; g.lineWidth = 1;
      const hgt = 18;
      g.beginPath(); g.moveTo(pw, yy); g.lineTo(pw + 6, yy - hgt / 2); g.lineTo(W - 2, yy - hgt / 2); g.lineTo(W - 2, yy + hgt / 2); g.lineTo(pw + 6, yy + hgt / 2); g.closePath(); g.fill(); if (!vul) g.stroke();
      g.fillStyle = vul ? "#071017" : kleur; g.font = font(11, 700); g.textAlign = "left"; g.textBaseline = "middle";
      g.fillText(tekst, pw + 9, yy + 0.5);
    };
    const label = (v, kleur, tekst) => {
      const yy = y(v);
      g.font = font(11, 700);
      const w = g.measureText(tekst).width + 14;
      const xx = 10, h = 19;
      g.fillStyle = "rgba(7, 14, 20, .88)"; g.strokeStyle = kleur; g.lineWidth = 1;
      if (g.roundRect) { g.beginPath(); g.roundRect(xx, yy - h / 2, w, h, 5); g.fill(); g.stroke(); }
      else { g.fillRect(xx, yy - h / 2, w, h); g.strokeRect(xx, yy - h / 2, w, h); }
      g.fillStyle = kleur; g.textAlign = "left"; g.textBaseline = "middle"; g.fillText(tekst, xx + 7, yy + 0.5);
    };

    // positielijnen
    const iv = d.instrument.valuta || "";
    const geplaatst = [];
    for (const l of lijnen) {
      if (!isNum(l.v) || l.v < lo || l.v > hi) continue;
      const yy = Math.round(y(l.v)) + 0.5;
      g.strokeStyle = l.k; g.lineWidth = l.t === "entry" ? 1.6 : 1.2; g.setLineDash(l.t === "entry" ? [] : [6, 4]);
      g.beginPath(); g.moveTo(0, yy); g.lineTo(pw, yy); g.stroke(); g.setLineDash([]);
      const p = l.p;
      let tekst;
      if (l.t === "entry") {
        const pnl = isNum(p.pnl_account) ? p.pnl_account : p.pnl;
        const v = isNum(p.pnl_account) ? (d.account.valuta || "") : iv;
        tekst = `${p.richting.toUpperCase()} ${fmt(p.units)} @ ${fmt(p.instap)}   ${fmtS(pnl)} ${v}`;
      } else if (l.t === "sl") tekst = `SL ${fmt(l.v)}  (${fmtS((p.richting === "long" ? l.v - p.instap : p.instap - l.v) * p.units)} ${iv})`;
      else tekst = `TP ${fmt(l.v)}  (${fmtS((p.richting === "long" ? l.v - p.instap : p.instap - l.v) * p.units)} ${iv})`;
      // labels niet over elkaar
      let ly = yy;
      for (const q of geplaatst) if (Math.abs(q - ly) < 21) ly = q + (ly >= q ? 21 : -21);
      geplaatst.push(ly);
      label(lo + (1 - (ly - TOP) / ph) * (hi - lo), l.k, tekst);
      tag(l.v, l.k, fmt(l.v), l.t === "entry");
    }

    // laatste koers
    const mid = d.koers.mid;
    const laatste = zicht[zicht.length - 1];
    this._laatsteCandle = cs[cs.length - 1];
    if (isNum(mid) && mid >= lo && mid <= hi) {
      const yy = Math.round(y(mid)) + 0.5;
      const k = laatste.c >= laatste.o ? KLEUR.op : KLEUR.neer;
      g.strokeStyle = k; g.globalAlpha = 0.7; g.setLineDash([2, 3]); g.lineWidth = 1;
      g.beginPath(); g.moveTo(0, yy); g.lineTo(pw, yy); g.stroke(); g.setLineDash([]); g.globalAlpha = 1;
      tag(mid, k, fmt(mid));
    }

    // crosshair
    const h = this._hover;
    let hov = null;
    if (h && h.x < pw && h.y > TOP && h.y < H - TB) {
      const i = Math.round((h.x - xs(0)) / zoom);
      const ii = Math.max(0, Math.min(zicht.length - 1, i));
      hov = zicht[ii];
      const xx = Math.round(xs(ii)) + 0.5, yy = Math.round(h.y) + 0.5;
      g.strokeStyle = KLEUR.kruis; g.setLineDash([4, 4]); g.lineWidth = 1;
      g.beginPath(); g.moveTo(xx, TOP); g.lineTo(xx, H - TB); g.moveTo(0, yy); g.lineTo(pw, yy); g.stroke(); g.setLineDash([]);
      const v = lo + (1 - (h.y - TOP) / ph) * (hi - lo);
      tag(v, "#d6e0e6", fmt(v));
      const tt = this._dhm(hov.t);
      g.font = font(11, 700);
      const tw = g.measureText(tt).width + 14;
      const tx = Math.max(tw / 2, Math.min(pw - tw / 2, xx));
      g.fillStyle = "#d6e0e6"; g.fillRect(tx - tw / 2, H - TB + 3, tw, TB - 6);
      g.fillStyle = "#071017"; g.textAlign = "center"; g.fillText(tt, tx, H - TB / 2 + 0.5);
    }
    if (d) this._renderGkop(d, hov);
  }
}

if (!customElements.get(ELEMENT_NAME)) {
  customElements.define(ELEMENT_NAME, GoldScalperBrokerPanel);
}
