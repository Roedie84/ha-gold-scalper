import { chromium } from 'PLAYWRIGHT_MODULE';
const dir = process.argv[2];
const b = await chromium.launch({ executablePath: process.env.PW_CHROMIUM });
let fout = 0;
for (const [naam, w, h, dpr] of [['desktop', 1496, 900, 1], ['mobiel', 390, 844, 2]]) {
  const pg = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: dpr });
  const fouten = [];
  pg.on('pageerror', (e) => fouten.push(String(e)));
  pg.on('console', (m) => { if (m.type() === 'error') fouten.push(m.text()); });
  await pg.goto('file://' + dir + '/broker_panel_v191.html');
  await pg.waitForTimeout(1200);
  const r = await pg.evaluate(() => {
    const host = document.querySelector('gold-scalper-broker-panel');
    const root = host.shadowRoot;
    const buiten = [];
    for (const kaart of root.querySelectorAll('.paneel, .tegel')) {
      const k = kaart.getBoundingClientRect();
      for (const el of kaart.querySelectorAll('*')) {
        const e = el.getBoundingClientRect();
        if (!e.width || !e.height) continue;
        if (e.right > k.right + 1 || e.left < k.left - 1) {
          buiten.push(`${kaart.className} > ${el.tagName.toLowerCase()}.${el.className && el.className.baseVal === undefined ? el.className : ''} [${Math.round(e.left)}-${Math.round(e.right)} vs ${Math.round(k.left)}-${Math.round(k.right)}] ${(el.textContent || '').slice(0, 40)}`);
        }
      }
    }
    const wrap = root.querySelector('.wrap').getBoundingClientRect();
    const rijen = [...root.querySelectorAll('#markt .rijen > div')].map((d) => d.textContent.slice(0, 30));
    return { buiten, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
      hostW: host.getBoundingClientRect().width, wrap: [wrap.left, wrap.right], rijen,
      waarom: [...root.querySelectorAll('#markt .rijen b')].map((x) => x.getBoundingClientRect().height) };
  });
  console.log(naam, 'scroll', r.sw, r.cw, 'host', r.hostW, 'wrap', r.wrap, 'buiten', r.buiten.length);
  r.buiten.slice(0, 15).forEach((x) => console.log('  ', x));
  if (r.buiten.length || r.sw > r.cw || fouten.length) fout = 1;
  if (fouten.length) console.log('console', fouten);
  if (Math.abs(r.wrap[1] - r.wrap[0] - Math.min(w, 1800)) > 1) { console.log('wrap vult breedte niet'); fout = 1; }
  if (naam === 'desktop') await pg.screenshot({ path: `${process.argv[3]}`, fullPage: true });
  else await pg.screenshot({ path: `${dir}/mobiel.png`, fullPage: true });
  await pg.close();
}
await b.close();
console.log(fout ? 'FOUT' : 'OK');
process.exitCode = fout;
