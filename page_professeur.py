"""Page web de la saisie des points (une seule page, adaptée à l'ordinateur, la tablette et le téléphone). Servie par serveur_notes.py.
Le texte venant du serveur est toujours inséré avec textContent (jamais en HTML) : aucune injection possible."""

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0A1E45">
<link rel="manifest" href="/professeur/manifest.webmanifest">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="GESTSCO">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/assets/gestsco_180.png">
<link rel="icon" type="image/png" href="/assets/gestsco_192.png">
<title>GESTSCO - Saisie des points</title>
<style>
:root{--nuit:#0A1E45;--bleu:#1D4ED8;--fond:#F4F6FB;--carte:#fff;--bord:#D7DEEE;--texte:#0F1B3D;--gris:#5B6785;--vert:#1E8E5A;--rouge:#C0392B;--orange:#D9822B;--violet:#6D4AC4}
@media (prefers-color-scheme:dark){:root{--fond:#0B1226;--carte:#131D3A;--bord:#2A3860;--texte:#E8EDFB;--gris:#9AA8CF;--nuit:#060D20}}
*{box-sizing:border-box}
html,body{margin:0;background:var(--fond);color:var(--texte);font:16px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{background:var(--nuit);color:#fff;padding:10px 16px;padding-top:calc(10px + env(safe-area-inset-top));display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:20}
header .titre{font-weight:700;flex:1;min-width:0}
header .titre small{display:block;font-weight:400;opacity:.75;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button,select,input{font:inherit;color:inherit}
.bouton{border:0;border-radius:8px;padding:10px 14px;font-weight:600;cursor:pointer;background:var(--bleu);color:#fff;min-height:44px}
.bouton.sec{background:transparent;color:var(--texte);border:1px solid var(--bord)}
.bouton.danger{background:var(--rouge)}
header .bouton{background:#183268;min-height:38px;padding:6px 12px}
.page{max-width:1200px;margin:0 auto;padding:12px 12px 40px}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:12px;padding:14px;margin-bottom:12px}
.centre{max-width:420px;margin:8vh auto 0}
.centre h1{font-size:20px;margin:0 0 4px}
label{display:block;font-size:13px;font-weight:600;color:var(--gris);margin:10px 0 4px}
input[type=text],input[type=password],select{width:100%;padding:10px 12px;border:1px solid var(--bord);border-radius:8px;background:var(--carte);min-height:44px}
.selecteurs{display:grid;grid-template-columns:repeat(2,1fr);gap:0 10px}
@media (min-width:760px){.selecteurs{grid-template-columns:repeat(5,1fr)}}
.barre{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
.barre .espace{flex:1}
.onglets{display:flex;gap:8px;margin-bottom:6px}
.onglet,.sousonglet{flex:1;border:1px solid var(--bord);background:transparent;color:var(--texte);border-radius:10px;padding:10px;font-weight:700;font-size:16px;min-height:46px;cursor:pointer}
.onglet.actif,.sousonglet.actif{background:var(--nuit);color:#fff;border-color:var(--nuit)}
.pt{border:1px solid var(--bord);background:transparent;color:var(--texte);border-radius:8px;padding:8px 14px;font-weight:700;min-height:42px;min-width:84px;cursor:pointer}
.pt.p.on{background:var(--vert);border-color:var(--vert);color:#fff}.pt.a.on{background:var(--rouge);border-color:var(--rouge);color:#fff}
.badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:13px;font-weight:700}
.badge.p{background:rgba(30,142,90,.16);color:var(--vert)}.badge.a{background:rgba(192,57,43,.16);color:var(--rouge)}.badge.n{color:var(--gris)}
td.c-p{background:rgba(30,142,90,.14)}td.c-a{background:rgba(192,57,43,.16)}
@media (max-width:620px){td.nom{white-space:normal}}
th.ev.actif{background:var(--bleu)}.info{margin:0 2px 8px;padding:8px 10px;border-radius:8px;background:rgba(217,130,43,.16);color:var(--texte);font-weight:600}
.message{margin:8px 0 0;font-weight:600;min-height:1.4em}
.message.ok{color:var(--vert)}.message.err{color:var(--rouge);white-space:pre-line}
.tableau{overflow:auto;max-height:68vh;border:1px solid var(--bord);border-radius:10px;background:var(--carte);-webkit-overflow-scrolling:touch}
table{border-collapse:separate;border-spacing:0;width:100%}
th,td{padding:6px 8px;border-bottom:1px solid var(--bord);text-align:center;white-space:nowrap}
thead th{position:sticky;top:0;background:var(--nuit);color:#fff;z-index:2;font-size:13px}
th.nom,td.nom{position:sticky;left:0;text-align:left;background:var(--carte);z-index:1;min-width:150px;max-width:210px;overflow:hidden;text-overflow:ellipsis;border-right:1px solid var(--bord)}
thead th.nom{background:var(--nuit);z-index:3}
tbody tr:nth-child(even) td{background:rgba(29,78,216,.04)}
tbody tr:nth-child(even) td.nom{background:var(--carte)}
td.num{color:var(--gris);width:34px}
th.ev{cursor:pointer;min-width:74px}
th.ev small{display:block;font-weight:400;opacity:.8;font-size:11px}
td input{width:66px;text-align:center;padding:8px 4px;border:1px solid var(--bord);border-radius:6px;background:var(--carte);min-height:40px}
td input.ok{border-color:var(--vert);background:rgba(30,142,90,.12)}
td input.err{border-color:var(--rouge);background:rgba(192,57,43,.14)}
td select{width:auto;min-width:66px;padding:6px;min-height:40px}
td.tot{font-weight:700}
.badge.cor{background:var(--rouge);color:#fff;margin-left:6px;padding:0 8px}
.corr{border:1px solid var(--bord);border-radius:10px;padding:10px 12px;margin:0 0 10px;background:var(--carte)}
.corr .tete{display:flex;flex-wrap:wrap;gap:4px 10px;justify-content:space-between;align-items:center}
.corr .meta{font-size:13px;color:var(--gris);margin:2px 0 0}
.corr .motif{margin:6px 0 0;white-space:pre-line}
.corr .rep{margin:6px 0 0;padding:6px 10px;border-left:3px solid var(--bleu);background:var(--fond);font-size:14px;white-space:pre-line}
.corr .barre{margin-top:8px}.corr input[type=text]{flex:1;min-width:200px}
.legende{font-size:13px;color:var(--gris)}
.legende b{color:var(--texte)}
.legende p{margin:4px 0}
.fond-modal{position:fixed;inset:0;background:rgba(0,0,0,.5);display:flex;align-items:center;justify-content:center;padding:16px;z-index:50}
.modal{background:var(--carte);border-radius:14px;padding:18px;width:100%;max-width:380px}
.modal h2{margin:0 0 6px;font-size:18px}
.modal .barre{justify-content:flex-end}
.cache{display:none!important}
.vide{padding:24px;text-align:center;color:var(--gris)}
@media (max-width:600px){
 .page{padding:8px 8px 30px}.carte{padding:10px}label{margin:6px 0 2px;font-size:12px}
 input[type=text],input[type=password],select{min-height:40px;padding:7px 8px}
 .selecteurs{gap:0 8px}.barre{gap:6px;margin-top:8px}.bouton{padding:8px 10px;min-height:40px}
 .long{display:none}.num,th.n{display:none}
 th.nom,td.nom{min-width:118px;max-width:132px;font-size:14px}
 td{padding:5px 4px}td input{width:58px}.message{margin-top:4px}
}
@media print{header,.selecteurs,.barre,.message{display:none}.tableau{max-height:none;overflow:visible}}
</style>
</head>
<body>

<div id="vue-login" class="page centre cache">
  <div class="carte">
    <img src="/assets/gestisc_96.png" alt="" width="64" height="64" style="display:block;margin:0 0 8px;border-radius:14px">
    <h1>GESTSCO</h1>
    <div style="color:var(--gris)">Système de Gestion Scolaire · Saisie des points et présence - Professeurs</div>
    <form id="f-login" autocomplete="on">
      <label for="login">Identifiant</label>
      <input type="text" id="login" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false">
      <label for="mdp">Mot de passe</label>
      <input type="password" id="mdp" name="password" autocomplete="current-password">
      <p class="message err" id="m-login"></p>
      <button class="bouton" style="width:100%" type="submit">Se connecter</button>
    </form>
  </div>
  <div class="carte" id="carte-installer" hidden>
    <b>Installer l'application</b>
    <p style="color:var(--gris);margin:6px 0 10px" id="installer-texte">Ajoutez GESTSCO à l'écran d'accueil : elle s'ouvre en plein écran, comme une application.</p>
    <button class="bouton" id="b-installer" type="button" hidden>Installer sur cet appareil</button>
    <ol id="aide-installer" hidden style="margin:6px 0 0;padding-left:20px"></ol>
  </div>
</div>

<div id="vue-mdp" class="page centre cache">
  <div class="carte">
    <h1>Nouveau mot de passe</h1>
    <div style="color:var(--gris)">Votre mot de passe est provisoire : choisissez le vôtre (12 caractères au moins, avec majuscule, minuscule, chiffre et symbole).</div>
    <form id="f-mdp">
      <label for="ancien">Mot de passe provisoire</label>
      <input type="password" id="ancien" autocomplete="current-password">
      <label for="nouveau">Nouveau mot de passe</label>
      <input type="password" id="nouveau" autocomplete="new-password">
      <label for="confirmation">Confirmer</label>
      <input type="password" id="confirmation" autocomplete="new-password">
      <p class="message err" id="m-mdp"></p>
      <button class="bouton" style="width:100%" type="submit">Enregistrer</button>
    </form>
  </div>
</div>

<div id="vue-app" class="cache">
  <header>
    <div class="titre"><span id="titre-page">GESTSCO - Saisie des points</span><small id="qui"></small></div>
    <button class="bouton" id="b-quitter">Déconnexion</button>
  </header>
  <div class="page">
    <div class="carte">
      <div class="onglets" id="onglets">
        <button class="onglet cache" data-mode="bulletins" id="o-classe">Ma classe</button>
        <button class="onglet actif" data-mode="points" id="o-points">Points</button>
        <button class="onglet" data-mode="presence" id="o-presence">Présence</button>
        <button class="onglet" data-mode="horaire" id="o-horaire">Horaire</button>
        <button class="onglet" data-mode="corrections" id="o-corrections">Corrections<span class="badge cor cache" id="nb-cor"></span></button>
      </div>
      <div class="selecteurs" id="sel-pts">
        <div><label for="s-annee">Année</label><select id="s-annee"></select></div>
        <div><label for="s-classe">Classe</label><select id="s-classe"></select></div>
        <div><label for="s-cours">Cours</label><select id="s-cours"></select></div>
        <div id="d-per"><label for="s-per">Saisir (autorisé par le titulaire)</label><select id="s-per"></select></div>
        <div id="d-jour" class="cache"><label for="s-jour">Date (jj/mm/aaaa)</label><input type="text" id="s-jour" inputmode="numeric" autocomplete="off"></div>
      </div>
      <div class="barre cache" id="barre-p">
        <button class="bouton sec" id="b-jour-moins" title="Jour précédent">&#9664;</button>
        <button class="bouton sec" id="b-aujourdhui">Aujourd'hui</button>
        <button class="bouton sec" id="b-jour-plus" title="Jour suivant">&#9654;</button>
        <button class="bouton" id="b-tous">Tous présents</button>
        <span class="espace"></span>
        <button class="bouton sec" id="b-hist">Présences du cours</button>
      </div>
      <div id="bloc-bul" class="cache">
        <div class="selecteurs" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
          <div><label for="b-annee">Année</label><select id="b-annee"></select></div>
          <div><label for="b-classe">Classe dont vous êtes titulaire</label><select id="b-classe"></select></div>
          <div><label for="b-portee">Résultats de</label><select id="b-portee"></select></div>
        </div>
        <div class="onglets" style="margin:10px 0 0" id="sous-onglets">
          <button class="sousonglet actif" id="v-eleves">Élèves de la classe</button>
          <button class="sousonglet" id="v-reussites">Réussites et échecs</button>
        </div>
        <div id="bloc-aut-d" style="margin-top:10px">
          <div class="barre" id="barre-bul" style="margin:0 0 10px">
            <button class="bouton" id="b-b-bul">Imprimer les bulletins validés de la classe (PDF)</button>
          </div>
          <div id="bloc-max" class="carte cache" style="margin:0 0 10px"></div>
          <div id="bloc-aut" class="carte" style="margin:0"></div>
        </div>
        <div class="barre cache" id="barre-reu">
          <button class="bouton" id="b-b-liste">Imprimer la liste des réussites et des échecs (PDF)</button>
          <button class="bouton sec" id="b-b-procl">Proclamation de l'année (PDF)</button>
        </div>
      </div>
      <div id="bloc-hor" class="cache">
        <div class="info" id="hor-info" style="margin-top:10px"></div>
        <div class="tableau" id="hor-tableau"></div>
      </div>
      <div id="bloc-cor" class="cache">
        <div class="info" id="cor-info" style="margin-top:10px"></div>
        <div id="cor-liste"></div>
      </div>
      <p class="message" id="message"></p>
    </div>
    <div id="zone"></div>
    <div class="carte legende" id="legende"></div>
  </div>
</div>

<script>
"use strict";
const $ = id => document.getElementById(id);
let jeton = null, D = null, F = null, mode = "points", histo = false, P = null, B = null, R = null, A = null, E = null, HO = null, vueClasse = "eleves", acces = {titulaire: false, enseigne: true};
try { jeton = sessionStorage.getItem("jeton"); } catch (e) {}

function h(tag, attrs, ...enfants) {
  const e = document.createElement(tag);
  for (const k in (attrs || {})) {
    if (k === "class") e.className = attrs[k]; else if (k.startsWith("on")) e.addEventListener(k.slice(2), attrs[k]);
    else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
  }
  for (const c of enfants.flat(Infinity)) if (c != null) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
function montrer(nom) { for (const v of ["vue-login", "vue-mdp", "vue-app"]) $(v).classList.toggle("cache", v !== nom); }
function msg(texte, ok) { const m = $("message"); m.textContent = texte || ""; m.className = "message " + (ok ? "ok" : "err"); }
function sauverJeton() { try { jeton ? sessionStorage.setItem("jeton", jeton) : sessionStorage.removeItem("jeton"); } catch (e) {} }
function fmt(n) { return n == null ? "" : String(n).replace(".", ","); }

async function api(methode, chemin, donnees) {
  const opts = {method: methode, headers: {}};
  if (jeton) opts.headers["Authorization"] = "Bearer " + jeton;
  let url = "/api/" + chemin;
  if (methode === "GET" && donnees) url += "?" + new URLSearchParams(donnees);
  if (methode === "POST") { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(donnees || {}); }
  let r;
  try { r = await fetch(url, opts); } catch (e) { throw new Error("Pas de connexion au serveur de l'école."); }
  let j = {};
  try { j = await r.json(); } catch (e) {}
  if (r.status === 401 && chemin !== "connexion") { deconnecterLocal("Session expirée : reconnectez-vous."); throw new Error(j.erreur || "Session expirée."); }
  if (!r.ok) throw new Error(j.erreur || "Erreur " + r.status);
  return j;
}
function deconnecterLocal(texte) { jeton = null; sauverJeton(); D = F = null; B = R = A = E = null; acces = {titulaire: false, enseigne: true}; vueClasse = "eleves"; mode = "points"; appliquerOnglets(); appliquerMode(); $("m-login").textContent = texte || ""; montrer("vue-login"); }

// ---------------------------------------------------------------- connexion
$("f-login").addEventListener("submit", async ev => {
  ev.preventDefault(); $("m-login").textContent = "";
  try {
    const r = await api("POST", "connexion", {login: $("login").value, mdp: $("mdp").value});
    jeton = r.jeton; sauverJeton(); $("mdp").value = "";
    if (r.doit_changer_mdp) montrer("vue-mdp"); else await demarrer(null, true);
  } catch (e) { $("m-login").textContent = e.message; }
});
$("f-mdp").addEventListener("submit", async ev => {
  ev.preventDefault(); $("m-mdp").textContent = "";
  try {
    await api("POST", "mdp", {ancien: $("ancien").value, nouveau: $("nouveau").value, confirmation: $("confirmation").value});
    for (const i of ["ancien", "nouveau", "confirmation"]) $(i).value = "";
    await demarrer(null, true);
  } catch (e) { $("m-mdp").textContent = e.message; }
});
$("b-quitter").addEventListener("click", async () => { try { await api("POST", "deconnexion"); } catch (e) {} deconnecterLocal(""); });

// ---------------------------------------------------------------- choix : année, classe, cours, semestre, période
async function demarrer(annee, premier) {
  D = await api("GET", "classes", annee ? {annee} : null);
  montrer("vue-app");
  $("qui").textContent = D.professeur;
  if (premier) {
    await lireAcces();
    appliquerOnglets();
    majCorrections();                                          // pastille : nombre de demandes ouvertes de la direction
    mode = acces.titulaire ? "bulletins" : "points";           // un titulaire arrive sur sa classe ; un professeur sur ses points
    appliquerMode();
  }
  const sa = $("s-annee"); sa.replaceChildren(...D.annees.map(a => h("option", {value: a}, a)));
  if (!D.annees.length) sa.append(h("option", {value: D.annee}, D.annee));
  sa.value = D.annee;
  const sc = $("s-classe");
  sc.replaceChildren(...D.classes.map(k => h("option", {value: k.n_classe}, k.designation + (k.option ? " - " + k.option : "") + " (" + k.nb_eleves + " élèves)")));
  choisirClasse();
  if (mode === "bulletins") { await chargerBulletins(); return; }
  if (!D.classes.length) { $("zone").replaceChildren(h("div", {class: "carte vide"}, "Aucun cours ne vous est attribué pour l'année " + D.annee + ". Voyez la direction des études.")); $("legende").replaceChildren(); }
  else if (!D.classes.some(k => (k.semestres || []).length)) { $("zone").replaceChildren(h("div", {class: "carte vide"}, "Le calendrier (semestres ou trimestres, et périodes) de l'année " + D.annee + " n'est pas encore défini pour vos classes.")); }
  else charger();
}
function classeCourante() { return D.classes.find(k => String(k.n_classe) === $("s-classe").value); }
function choisirClasse() {
  const k = classeCourante(), sc = $("s-cours");
  sc.replaceChildren(...(k ? k.cours : []).map(c => h("option", {value: c.id_cc}, c.cours)));
  choisirPeriode();
}
function aujourdhui() { const d = new Date(); return [("0" + d.getDate()).slice(-2), ("0" + (d.getMonth() + 1)).slice(-2), d.getFullYear()].join("/"); }
function enDate(t) { const m = /^(\d\d)\/(\d\d)\/(\d{4})$/.exec(t); return m ? new Date(+m[3], +m[2] - 1, +m[1]) : null; }
// Le professeur ne voit que les périodes et examens que le titulaire de la classe a autorisés.
function choisirPeriode() {
  const k = classeCourante(), ok = new Set(k ? k.autorisees : []), sp = $("s-per"), avant = sp.value, options = [];
  for (const s of (k ? k.semestres : D.semestres)) {                 // le calendrier de la section de la classe
    for (const p of s.periodes) if (ok.has(p.cle)) options.push(h("option", {value: p.id}, s.libelle + " - " + p.libelle));
    if (s.examen && ok.has(s.examen.cle)) options.push(h("option", {value: s.examen.id}, s.libelle + " - Examen"));
  }
  sp.replaceChildren(...options);
  if (options.some(o => o.value === avant)) sp.value = avant;
}
$("s-annee").addEventListener("change", () => demarrer($("s-annee").value).catch(e => msg(e.message)));
$("s-classe").addEventListener("change", () => { choisirClasse(); charger(); });
$("s-cours").addEventListener("change", charger);
$("s-per").addEventListener("change", charger);

async function charger() {
  if (mode === "bulletins") return;
  msg("");
  const cc = $("s-cours").value, per = $("s-per").value;
  if (mode === "points" && cc && !per) {
    F = null; $("zone").replaceChildren(h("div", {class: "carte vide"}, "Le titulaire de cette classe n'a encore ouvert aucune période ni aucun examen à la saisie. Demandez-lui d'autoriser la période à saisir."));
    $("legende").replaceChildren(); return;
  }
  if (!cc) { $("zone").replaceChildren(); return; }
  try {
    if (mode === "presence") { histo ? await chargerHistorique(cc) : (P = await api("GET", "presence/liste", {cc, date: $("s-jour").value}), dessinerPresence()); }
    else { F = await api("GET", "fiche", {cc, per}); dessiner(); }
  } catch (e) { msg(e.message); }
}

// ---------------------------------------------------------------- tableau de saisie
// Le professeur ne voit que le nom des élèves, le point de la période (ou de l'examen) autorisée et la conduite.
function peutSaisir() { return F.modifiable; }
function dessiner() {
  const saisie = peutSaisir(), periode = F.periode.genre === "P";
  const tete = h("tr", null, h("th", {class: "n"}, "N°"), h("th", {class: "nom"}, "Élève"),
    ...F.evaluations.map(c => h("th", {class: "ev actif", title: c.libelle}, c.code, h("small", null, "/" + fmt(c.maximum)))),
    periode ? h("th", null, "CDT") : null);
  const lignes = F.eleves.map((e, i) => {
    const tr = h("tr", {"data-m": e.matricule});
    tr.append(h("td", {class: "num"}, i + 1), h("td", {class: "nom", title: e.nom_complet}, e.nom_complet));
    for (const c of F.evaluations) {
      const inp = h("input", {type: "text", inputmode: "decimal", autocomplete: "off", "aria-label": e.nom_complet + " " + c.code,
        value: fmt(e.points[c.cle]), disabled: !saisie, "data-i": i});
      inp.addEventListener("change", () => enregistrerPoint(e, c, inp));
      inp.addEventListener("keydown", k => { if (k.key === "Enter") { k.preventDefault(); const s = document.querySelector('input[data-i="' + (i + 1) + '"]'); s ? (s.focus(), s.select()) : inp.blur(); } });
      inp.addEventListener("focus", () => inp.select());
      tr.append(h("td", null, inp));
    }
    if (periode) {
      const sel = h("select", {"aria-label": "Conduite de " + e.nom_complet, disabled: !saisie}, h("option", {value: ""}, "-"),
        ...F.legende.conduite.map(c => h("option", {value: c.code}, c.code)));
      sel.value = e.conduite;
      sel.addEventListener("change", () => enregistrerConduite(e, sel));
      tr.append(h("td", null, sel));
    }
    return tr;
  });
  const corps = F.eleves.length ? h("div", {class: "tableau"}, h("table", null, h("thead", null, tete), h("tbody", null, lignes)))
                                : h("div", {class: "carte vide"}, "Aucun élève n'est inscrit dans cette classe.");
  const titre = h("div", {style: "margin:0 2px 8px;font-weight:600"}, F.cours + " - " + F.classe + (F.option ? " - " + F.option : "") + "  |  " + F.periode.semestre + " : " + F.periode.libelle);
  const avis = !F.modifiable ? "L'année " + F.annee + " est désactivée : on n'y saisit plus de points." : null;
  $("zone").replaceChildren(titre, ...(avis ? [h("div", {class: "info"}, avis)] : []), corps);
  dessinerLegende();
}
function dessinerLegende() {
  const L = F ? F.legende : D.legende;
  $("legende").replaceChildren(h("p", null, h("b", null, "Conduite (CDT) : "), L.conduite.map(c => [h("b", null, c.code), " = " + c.libelle.toLowerCase() + "   "])),
    h("p", null, "Vous saisissez les points et la conduite de la période (ou de l'examen) que le titulaire de la classe a autorisée : un seul point par élève. Un point vide = pas de note (absent, pas corrigé). Écrivez le point puis appuyez sur Entrée : il est enregistré et le curseur descend à l'élève suivant."));
}
async function enregistrerPoint(e, c, inp) {
  inp.className = "";
  const t = inp.value.trim().replace(",", ".");
  if (t !== "" && (!/^\d{1,4}(\.\d{1,2})?$/.test(t) || parseFloat(t) > c.maximum)) {
    inp.className = "err"; msg(e.nom_complet + " : le point doit être entre 0 et " + fmt(c.maximum) + "."); return;
  }
  try {
    await api("POST", "points", {cc: F.id_cc, per: $("s-per").value, valeurs: {[e.matricule]: t}});
    e.points[c.cle] = t === "" ? null : parseFloat(t);
    inp.value = fmt(e.points[c.cle]); inp.className = "ok"; msg("");
    setTimeout(() => { if (inp.className === "ok") inp.className = ""; }, 1200);
  } catch (x) { inp.className = "err"; msg(x.message); }
}
async function enregistrerConduite(e, sel) {
  try { await api("POST", "conduite", {cc: F.id_cc, per: F.periode.id, matricule: e.matricule, cote: sel.value}); e.conduite = sel.value; msg(""); }
  catch (x) { sel.value = e.conduite; msg(x.message); }
}


// ---------------------------------------------------------------- ma classe : autorisations de saisie, résultats et bulletins (titulaire)
// L'onglet n'existe que pour un titulaire de classe ; le serveur refuse de toute façon les autres professeurs.
// Le titulaire ne modifie jamais les points des professeurs : il autorise la période à saisir, consulte les résultats et imprime.
async function lireAcces() {
  try { acces = await api("GET", "bulletins/acces"); } catch (e) { acces = {titulaire: false, enseigne: true}; }
}
// Qui voit quoi : « Ma classe » seulement pour un titulaire ; « Points » et « Présence » seulement pour qui a des cours.
// Un titulaire qui n'enseigne pas ne voit donc ni les points ni la présence ; un titulaire qui enseigne a les trois onglets.
function appliquerOnglets() {
  $("o-classe").classList.toggle("cache", !acces.titulaire);
  $("o-points").classList.toggle("cache", !acces.enseigne);
  $("o-presence").classList.toggle("cache", !acces.enseigne);
  $("o-horaire").classList.toggle("cache", !acces.enseigne);        // l'horaire publié des cours que le professeur donne
  $("o-corrections").classList.toggle("cache", !acces.enseigne);    // les demandes de la direction des études pour ses cours
  const nb = (acces.titulaire ? 1 : 0) + (acces.enseigne ? 4 : 0);
  $("onglets").classList.toggle("cache", nb < 2 || (acces.titulaire && !acces.enseigne));
  $("titre-page").textContent = acces.titulaire && !acces.enseigne ? "GESTSCO - Espace du titulaire"
    : acces.titulaire ? "GESTSCO - Espace enseignant" : "GESTSCO - Saisie des points";
}
function libClasse(k) { return k.designation + (k.option ? " - " + k.option : ""); }
async function chargerBulletins(annee) {
  msg("");
  try { B = await api("GET", "bulletins/classes", annee ? {annee} : null); }
  catch (e) { $("zone").replaceChildren(); msg(e.message); return; }
  $("b-annee").replaceChildren(...B.annees.map(a => h("option", {value: a}, a))); $("b-annee").value = B.annee;
  const ancienne = $("b-classe").value, ancienne_p = $("b-portee").value;
  $("b-classe").replaceChildren(...B.classes.map(k => h("option", {value: k.n_classe}, libClasse(k) + " (" + k.nb_eleves + " élèves)")));
  if (B.classes.some(k => String(k.n_classe) === ancienne)) $("b-classe").value = ancienne;
  const kcl = B.classes.find(k => String(k.n_classe) === $("b-classe").value);
  const portees = kcl ? kcl.portees : B.portees;                       // les périodes de la section de la classe (trimestres au primaire)
  $("b-portee").replaceChildren(...portees.map(p => h("option", {value: p.cle}, p.type === "periode" ? p.semestre + " - " + p.libelle : p.libelle)));
  const kc = B.classes.find(k => String(k.n_classe) === $("b-classe").value);
  const defaut = portees.some(p => p.cle === ancienne_p) ? ancienne_p : (kc && kc.portee_defaut) || (portees.length ? portees[portees.length - 1].cle : "");
  $("b-portee").value = defaut;
  E = null;
  await resultatsBulletins();
}
// Liste de la classe : toujours affichée, même si les semestres et périodes ne sont pas encore définis.
async function resultatsBulletins() {
  msg(""); E = null;
  $("barre-reu").classList.toggle("cache", vueClasse !== "reussites");
  $("v-eleves").classList.toggle("actif", vueClasse === "eleves"); $("v-reussites").classList.toggle("actif", vueClasse === "reussites");
  if (!B || !B.classes.length) { $("bloc-aut-d").classList.add("cache"); $("zone").replaceChildren(h("div", {class: "carte vide"}, "Vous n'êtes titulaire d'aucune classe pour cette année.")); return; }
  $("bloc-aut-d").classList.remove("cache");
  await chargerMaxima();
  await chargerAutorisations();
  try {
    R = await api("GET", "bulletins/resultats", {annee: B.annee, classe: $("b-classe").value, portee: $("b-portee").value, ordre: vueClasse === "eleves" ? "alpha" : "reussite"});
    dessinerClasse();
  } catch (e) { $("zone").replaceChildren(); msg(e.message); }
}
function badgeResultat(l) { return h("span", {class: "badge " + (l.reussite === true ? "p" : l.reussite === false ? "a" : "n")}, l.resultat); }
function enteteClasse() {
  const p = R.portee, s = R.stats;
  return h("div", {style: "margin:0 2px 8px;font-weight:600"}, libClasse(R.classe) + "  |  Année " + R.annee + "  |  " + R.lignes.length + " élève(s)" +
    (p && s ? "  |  " + p.libelle + " : réussites " + s.reussis + ", échecs " + s.echecs + (s.en_attente ? ", en attente " + s.en_attente : "") +
      (s.taux == null ? "" : ", taux de réussite " + fmt(s.taux) + " %") + (s.moyenne == null ? "" : ", moyenne de la classe " + fmt(s.moyenne) + " %") : ""));
}
function infoProclamation() {
  const q = R && R.proclamation;
  if (!q || !R.portee) return document.createTextNode("");
  return h("div", {class: "info", style: "margin:0 2px 8px"}, "Proclamation : " + q.libelle + ". " + (q.imprimable
    ? q.nb_valides + " bulletin(s) validé(s) : vous pouvez les imprimer. Les autres, vous pouvez seulement les consulter."
    : "Vous pouvez consulter les bulletins ; l'impression sera possible pour les bulletins validés quand le Préfet aura confirmé la proclamation."));
}
function dessinerClasse() {
  if (vueClasse === "eleves") dessinerEleves(); else dessinerReussites();
}
// Vue 1 : les élèves de la classe ; un clic sur un élève ouvre ses cotes de tous les cours.
function dessinerEleves() {
  const p = R.portee;
  const tete = h("tr", null, h("th", {class: "n"}, "N°"), h("th", {class: "nom"}, "Élève"), h("th", null, "Sexe"),
    p ? h("th", null, "% (" + p.libelle + ")") : null, p ? h("th", null, "Résultat") : null, p && R.proclamation ? h("th", null, "Bulletin") : null, h("th", null, "Cotes"));
  const lignes = R.lignes.map((l, i) => h("tr", {style: "cursor:pointer", onclick: () => ouvrirEleve(l.matricule)},
    h("td", {class: "num"}, i + 1), h("td", {class: "nom", title: l.nom_complet}, l.nom_complet), h("td", null, l.sexe || "-"),
    p ? h("td", {class: "tot"}, l.pct == null ? "-" : fmt(l.pct)) : null, p ? h("td", null, badgeResultat(l)) : null,
    p && R.proclamation ? h("td", null, h("span", {class: "badge " + (l.valide ? "p" : "n")}, l.valide ? "Validé" : "Non validé")) : null,
    h("td", null, h("button", {class: "bouton sec", style: "min-height:34px;padding:4px 10px", onclick: ev => { ev.stopPropagation(); ouvrirEleve(l.matricule); }}, "Voir les cotes"))));
  const corps = R.lignes.length ? h("div", {class: "tableau"}, h("table", null, h("thead", null, tete), h("tbody", null, lignes)))
                                : h("div", {class: "carte vide"}, "Aucun élève n'est inscrit dans cette classe pour l'année " + R.annee + ".");
  const blocs = [enteteClasse(), infoProclamation(), h("div", {style: "margin:0 2px 8px;color:var(--gris);font-size:13px"}, "Touchez un élève pour consulter ses cotes dans tous les cours de la classe."), corps];
  if (!R.portee) blocs.push(h("div", {class: "info", style: "margin-top:10px"}, "Les semestres (ou trimestres) et périodes de l'année " + B.annee + " ne sont pas encore définis : les résultats apparaîtront quand la direction des études les aura créés."));
  $("zone").replaceChildren(...blocs);
  $("legende").replaceChildren();
}
// Vue 2 : réussites d'abord (du premier au dernier), puis les échecs, puis les élèves en attente.
function dessinerReussites() {
  const p = R.portee, per = p && p.type === "periode";
  if (!p) { dessinerEleves(); return; }
  const tete = h("tr", null, h("th", null, "Rang"), h("th", {class: "nom"}, "Élève"), h("th", null, "Points"), h("th", null, "%"), h("th", null, "Mention"),
    h("th", null, "Résultat"), per ? h("th", null, "CDT") : null);
  let dernier = null;
  const lignes = [];
  for (const l of R.lignes) {
    const g = l.reussite === true ? "RÉUSSITES" : l.reussite === false ? "ÉCHECS" : "EN ATTENTE";
    if (g !== dernier) { lignes.push(h("tr", null, h("td", {colspan: per ? 7 : 6, style: "text-align:left;font-weight:700;background:rgba(29,78,216,.10)"}, g))); dernier = g; }
    lignes.push(h("tr", {style: "cursor:pointer", onclick: () => ouvrirEleve(l.matricule)},
      h("td", null, l.rang == null ? "-" : l.rang), h("td", {class: "nom", title: l.nom_complet}, l.nom_complet),
      h("td", null, l.max == null ? "-" : fmt(l.obtenu) + "/" + fmt(l.max)), h("td", {class: "tot"}, l.pct == null ? "-" : fmt(l.pct)),
      h("td", null, l.mention || "-"), h("td", null, badgeResultat(l)), per ? h("td", null, l.conduite || "-") : null));
  }
  const corps = R.lignes.length ? h("div", {class: "tableau"}, h("table", null, h("thead", null, tete), h("tbody", null, lignes)))
                                : h("div", {class: "carte vide"}, "Aucun élève n'est inscrit dans cette classe.");
  const blocs = [enteteClasse(), infoProclamation(), corps];
  if (R.alertes.length) {
    const max = 12;
    blocs.push(h("div", {class: "carte", style: "margin-top:12px"}, h("b", null, "À vérifier avant d'imprimer (" + R.alertes.length + ")"),
      ...R.alertes.slice(0, max).map(a => h("div", {style: "margin-top:4px;color:var(--gris)"}, "• " + a)),
      R.alertes.length > max ? h("div", {style: "margin-top:4px;color:var(--gris)"}, "… et " + (R.alertes.length - max) + " autre(s).") : null));
  }
  blocs.push(h("div", {class: "carte legende", style: "margin-top:12px"}, h("p", null, "Seuil de réussite : " + fmt(R.seuil) + " %. Le pourcentage est calculé sur les points des évaluations notées de chaque élève. " +
    "Tant qu'il manque les points d'une période, le résultat reste « en attente »."), h("p", null, "Vous seul (titulaire) voyez cet onglet. Vous ne modifiez pas les points saisis par les professeurs.")));
  $("zone").replaceChildren(...blocs);
  $("legende").replaceChildren();
}
// Cotes d'un élève : tous les cours de la classe, par période, examen, semestre et année.
async function ouvrirEleve(matricule) {
  msg("");
  try { E = await api("GET", "bulletins/eleve", {annee: B.annee, classe: $("b-classe").value, matricule}); }
  catch (e) { msg(e.message); return; }
  dessinerEleve();
  window.scrollTo({top: 0});
}
function celluleCote(c) {
  if (!c) return h("td", null, "-");
  return h("td", null, fmt(c.obtenu) + "/" + fmt(c.max), h("small", {style: "display:block;color:var(--gris)"}, c.pct == null ? "" : fmt(c.pct) + " %"));
}
function dessinerEleve() {
  const cols = E.colonnes, el = E.eleve;
  const ordre = R ? R.lignes.map(l => l.matricule) : [], pos = ordre.indexOf(el.matricule);
  const aller = m => () => ouvrirEleve(m);
  const lr = R ? R.lignes.find(x => x.matricule === el.matricule) : null;
  const imprimable = !R || !R.proclamation || !!(R.proclamation.imprimable && lr && lr.valide);
  const barre = h("div", {class: "barre", style: "margin:0 0 10px"},
    h("button", {class: "bouton sec", onclick: () => dessinerClasse()}, "← Retour à la liste"),
    h("span", {class: "espace"}),
    h("button", {class: "bouton", disabled: !imprimable, onclick: () => ouvrirPdf("bulletin", el.matricule),
      title: imprimable ? "Imprimer le bulletin validé de cet élève" : "Bulletin non validé ou proclamation pas encore confirmée : consultation seulement"}, "Bulletin (PDF)"),
    h("button", {class: "bouton sec", disabled: pos <= 0, onclick: pos > 0 ? aller(ordre[pos - 1]) : null, title: "Élève précédent"}, "◀"),
    h("button", {class: "bouton sec", disabled: pos < 0 || pos >= ordre.length - 1, onclick: pos >= 0 && pos < ordre.length - 1 ? aller(ordre[pos + 1]) : null, title: "Élève suivant"}, "▶"));
  const tete = h("tr", null, h("th", {class: "nom"}, "Cours"),
    ...cols.map(c => h("th", {title: c.semestre ? c.semestre + " - " + c.libelle : c.libelle}, c.type === "examen" ? "Examen " + c.semestre.replace(/ semestre/, " sem.") : c.libelle)));
  const lignes = E.cours.map(c => h("tr", null, h("td", {class: "nom", title: c.libelle + (c.professeur ? " - " + c.professeur : "")}, c.libelle),
    ...cols.map(k => celluleCote(c.cotes[k.cle]))));
  const t = E.totaux;
  const total = h("tr", null, h("td", {class: "nom tot"}, "TOTAL"), ...cols.map(k => { const x = t[k.cle];
    return h("td", {class: "tot"}, x.max == null ? "-" : fmt(x.obtenu) + "/" + fmt(x.max), h("small", {style: "display:block;color:var(--gris)"}, x.pct == null ? "" : fmt(x.pct) + " %")); }));
  const rang = h("tr", null, h("td", {class: "nom"}, "Rang (sur " + E.effectif + ")"), ...cols.map(k => h("td", null, t[k.cle].rang == null ? "-" : t[k.cle].rang)));
  const res = h("tr", null, h("td", {class: "nom"}, "Résultat"), ...cols.map(k => h("td", null, badgeResultat(t[k.cle]))));
  const cdt = h("tr", null, h("td", {class: "nom"}, "Conduite"), ...cols.map(k => h("td", null, k.type === "periode" ? (t[k.cle].conduite || "-") : "")));
  const corps = E.cours.length ? h("div", {class: "tableau"}, h("table", null, h("thead", null, tete), h("tbody", null, lignes, total, rang, res, cdt)))
                               : h("div", {class: "carte vide"}, "Aucun cours n'est ouvert dans cette classe pour cette année.");
  $("zone").replaceChildren(barre,
    h("div", {style: "margin:0 2px 8px;font-weight:700;font-size:18px"}, el.nom_complet),
    h("div", {style: "margin:0 2px 10px;color:var(--gris)"}, libClasse(E.classe) + "  |  Année " + E.annee + (el.matricule ? "  |  Matricule " + el.matricule : "")),
    corps,
    h("div", {class: "carte legende", style: "margin-top:12px"}, h("p", null, "Les cotes sont celles saisies par les professeurs de chaque cours (points obtenus / maximum, puis pourcentage). Seuil de réussite : " + fmt(E.seuil) + " %. Lecture seule : vous ne modifiez pas les cotes.")));
}
async function ouvrirPdf(genre, matricule) {
  if (!B || !R) return;
  msg("Préparation du document...", true);
  try {
    const q = new URLSearchParams({genre, annee: B.annee, classe: $("b-classe").value, portee: $("b-portee").value});
    if (matricule) q.set("matricule", matricule);
    const r = await fetch("/api/bulletins/pdf?" + q, {headers: {"Authorization": "Bearer " + jeton}});
    if (r.status === 401) { deconnecterLocal("Session expirée : reconnectez-vous."); return; }
    if (!r.ok) { let j = {}; try { j = await r.json(); } catch (e) {} throw new Error(j.erreur || "Erreur " + r.status); }
    const u = URL.createObjectURL(await r.blob());
    const a = h("a", {href: u, target: "_blank", rel: "noopener"}); document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 120000);
    msg("Document ouvert : imprimez-le ou enregistrez-le depuis le lecteur PDF du navigateur.", true);
  } catch (e) { msg(e.message); }
}
// Maximum de chaque cours de la classe (secondaire et humanités) : fixé par le titulaire ; examen = 2 x période, semestre = 4 x, année = 8 x.
async function chargerMaxima() {
  const zone = $("bloc-max");
  let M;
  try { M = await api("GET", "bulletins/maxima", {annee: B.annee, classe: $("b-classe").value}); }
  catch (e) { zone.classList.remove("cache"); zone.replaceChildren(h("div", {class: "info"}, e.message)); return; }
  if (!M.modifiable) { zone.classList.add("cache"); return; }          // primaire : pas de maxima à régler
  zone.classList.remove("cache");
  const ligne = c => {
    const champ = h("input", {type: "number", min: "1", max: "500", step: "any", value: String(c.maximum), inputmode: "decimal",
                              style: "width:90px;min-height:38px;padding:4px 8px;border:1px solid var(--bord);border-radius:8px;font-size:16px"});
    const note = h("small", {style: "color:var(--gris)"}, c.sans_examen ? "sans examen" : "examen sur " + fmt(c.maximum * 2));
    const b = h("button", {class: "bouton sec", style: "min-height:38px;padding:4px 12px"}, "Enregistrer");
    champ.addEventListener("input", () => { note.textContent = Number(champ.value) >= 100 ? "sans examen" : "examen sur " + fmt(Number(champ.value) * 2); });
    b.addEventListener("click", async () => {
      try { await api("POST", "bulletins/maximum", {annee: M.annee, classe: M.n_classe, cc: c.id_cc, maximum: champ.value}); await chargerMaxima(); msg("Maximum enregistré : " + c.libelle + ".", true); }
      catch (e) { msg(e.message); }
    });
    return h("div", {style: "display:flex;align-items:center;gap:10px;margin:6px 0;flex-wrap:wrap"},
      h("span", {style: "flex:1;min-width:160px"}, c.libelle, c.professeur ? h("small", {style: "display:block;color:var(--gris)"}, c.professeur) : null),
      champ, note, b);
  };
  zone.replaceChildren(h("b", null, "Maximum de chaque cours - " + M.classe),
    h("div", {style: "color:var(--gris);margin:2px 0 6px;font-size:13px"}, "Vous fixez le maximum d'une période pour chaque cours de votre classe (ex. 10, 20, 40, 50, 100). L'examen vaut le double, le semestre 4 fois et l'année 8 fois ce maximum. Les professeurs saisissent leurs points sur ces maxima, qui sont imprimés sur le bulletin. Sans votre choix, le maximum est 20. Un maximum de 100 ou plus (atelier, laboratoire) n'a pas d'examen."),
    ...(M.cours.length ? M.cours.map(ligne) : [h("div", {class: "info"}, "Aucun cours n'est ouvert dans cette classe pour cette année.")]));
}
async function chargerAutorisations() {
  const zone = $("bloc-aut");
  try { A = await api("GET", "bulletins/autorisations", {annee: B.annee, classe: $("b-classe").value}); }
  catch (e) { zone.replaceChildren(h("div", {class: "info"}, e.message)); return; }
  if (A.primaire) {                                            // primaire : l'unique enseignant n'a personne à autoriser
    zone.replaceChildren(h("b", null, "Saisie des points - " + A.classe),
      h("div", {style: "color:var(--gris);margin:4px 0 0;font-size:13px"}, "Au primaire, vous êtes l'unique enseignant de la classe : tous les cours vous sont attribués et toutes les périodes et tous les examens sont ouverts à votre saisie (onglet « Points »)."));
    return;
  }
  const ligne = x => {
    const b = h("button", {class: "pt " + (x.autorisee ? "p on" : ""), "aria-pressed": x.autorisee ? "true" : "false"}, x.autorisee ? "Ouverte" : "Fermée");
    b.addEventListener("click", async () => {
      try { await api("POST", "bulletins/autoriser", {annee: A.annee, classe: A.n_classe, cle: x.cle, autorisee: !x.autorisee}); await chargerAutorisations(); msg(""); }
      catch (e) { msg(e.message); }
    });
    return h("div", {style: "display:flex;align-items:center;gap:10px;margin:6px 0"}, h("span", {style: "flex:1"}, x.type === "examen" ? "Examen" : x.libelle), b);
  };
  const blocs = [];                                              // un bloc par semestre : ses périodes, puis son examen
  for (const sem of [...new Set(A.elements.map(x => x.semestre))])
    blocs.push(h("div", {style: "margin-top:10px;padding:8px 10px;border:1px solid var(--bord);border-radius:10px"},
      h("div", {style: "font-weight:700"}, sem), ...A.elements.filter(x => x.semestre === sem).map(ligne)));
  zone.replaceChildren(h("b", null, "Semestres et périodes ouverts à la saisie des professeurs - " + A.classe),
    h("div", {style: "color:var(--gris);margin:2px 0 0;font-size:13px"}, "Choisissez la période (ou l'examen) de chaque semestre que les professeurs de votre classe peuvent saisir : points et conduite. Fermer n'efface rien."),
    ...(blocs.length ? blocs : [h("div", {class: "info", style: "margin-top:8px"}, "Les semestres et périodes de l'année " + A.annee + " ne sont pas encore définis (Direction des études > Années et périodes).")]));
}
$("b-annee").addEventListener("change", () => chargerBulletins($("b-annee").value));
$("b-classe").addEventListener("change", () => { E = null; chargerBulletins($("b-annee").value); });   // le calendrier dépend de la section de la classe
$("b-portee").addEventListener("change", () => { E = null; resultatsBulletins(); });
$("v-eleves").addEventListener("click", () => { vueClasse = "eleves"; resultatsBulletins(); });
$("v-reussites").addEventListener("click", () => { vueClasse = "reussites"; resultatsBulletins(); });
$("b-b-bul").addEventListener("click", () => ouvrirPdf("bulletins"));
$("b-b-liste").addEventListener("click", () => ouvrirPdf("liste"));
$("b-b-procl").addEventListener("click", () => ouvrirPdf("proclamation"));

// ---------------------------------------------------------------- présence des élèves au cours
for (const b of document.querySelectorAll(".onglet")) b.addEventListener("click", () => changerMode(b.dataset.mode));
function appliquerMode() {
  const bul = mode === "bulletins", pres = mode === "presence", hor = mode === "horaire", cor = mode === "corrections";
  for (const b of document.querySelectorAll(".onglet")) b.classList.toggle("actif", b.dataset.mode === mode);
  $("sel-pts").classList.toggle("cache", bul || hor || cor);
  $("legende").classList.toggle("cache", bul || hor || cor);
  $("bloc-bul").classList.toggle("cache", !bul);
  $("bloc-hor").classList.toggle("cache", !hor);
  $("bloc-cor").classList.toggle("cache", !cor);
  $("barre-p").classList.toggle("cache", bul || hor || cor || !pres);
  $("d-per").classList.toggle("cache", pres);
  $("d-jour").classList.toggle("cache", !pres);
}
function changerMode(m) {
  mode = m; histo = false;
  appliquerMode();
  if (m === "presence" && !$("s-jour").value) $("s-jour").value = aujourdhui();
  $("b-hist").textContent = "Présences du cours";
  if (m === "bulletins") chargerBulletins(); else if (m === "horaire") chargerHoraire(); else if (m === "corrections") chargerCorrections(); else charger();
}

// ---------------------------------------------------------------- horaire : l'horaire PUBLIÉ par la direction des études (lecture seule)
async function chargerHoraire() {
  msg(""); $("zone").replaceChildren(); $("legende").replaceChildren();
  try { HO = await api("GET", "horaire/mien"); } catch (e) { HO = null; $("hor-tableau").replaceChildren(); $("hor-info").textContent = ""; msg(e.message); return; }
  dessinerHoraire();
}
function dessinerHoraire() {
  $("hor-info").textContent = HO.nb_seances
    ? "Année " + HO.annee + " : " + HO.nb_seances + " cours par semaine."
    : "Aucun horaire publié pour vous pour l'année " + HO.annee + ". La direction des études vous le signalera dès sa publication.";
  if (!HO.nb_seances) { $("hor-tableau").replaceChildren(); return; }
  const tete = h("tr", {}, h("th", {class: "nom"}, "Heure"), HO.jours.map(j => h("th", {}, j.nom)));
  const lignes = HO.lignes.map(l => h("tr", {}, h("td", {class: "nom"}, l.debut + " – " + l.fin),
    HO.jours.map(j => h("td", {}, (l.cases[j.index] || []).map(x => h("div", {}, h("b", {}, x.classe), " ", x.cours))))));
  $("hor-tableau").replaceChildren(h("table", {}, h("thead", {}, tete), h("tbody", {}, lignes)));
}
// ---------------------------------------------------------------- corrections : les demandes de la direction des études pour mes cours
// Le professeur corrige LUI-MÊME ses points (onglet Points), puis marque la demande « traitée » avec sa réponse.
let COR = null;
async function majCorrections() {
  try { COR = await api("GET", "corrections"); } catch (e) { return false; }
  const b = $("nb-cor"); b.textContent = COR.nb_ouvertes ? String(COR.nb_ouvertes) : ""; b.classList.toggle("cache", !COR.nb_ouvertes);
  return true;
}
async function chargerCorrections() {
  msg(""); $("zone").replaceChildren(); $("legende").replaceChildren();
  if (!(await majCorrections())) { $("cor-liste").replaceChildren(); $("cor-info").textContent = ""; msg("Impossible de lire les demandes pour le moment."); return; }
  dessinerCorrections();
}
function titreCorrection(d) { return d.type_libelle + " · " + d.classe + " · " + d.cours + " · " + d.periode + (d.eleve ? " · " + d.eleve : ""); }
function carteOuverte(d) {
  const rep = h("input", {type: "text", maxlength: "1000", "aria-label": "Votre réponse à la direction",
    placeholder: d.type === "CORRECTION" ? "Ce que vous avez corrigé" : "Si des notes restent manquantes : pourquoi (élève absent...)"});
  const bt = h("button", {class: "bouton", type: "button", onclick: async () => {
    bt.disabled = true;
    try { await api("POST", "corrections/traiter", {id: d.id, reponse: rep.value}); await chargerCorrections(); msg("Demande marquée comme traitée.", true); }
    catch (x) { msg(x.message); bt.disabled = false; }
  }}, "Marquer comme traitée");
  return h("div", {class: "corr"},
    h("div", {class: "tete"}, h("b", {}, titreCorrection(d))),
    h("div", {class: "meta"}, "Demande du " + d.date + " (" + d.par + ")"),
    h("p", {class: "motif"}, d.motif),
    !d.saisie_ouverte ? h("div", {class: "info", style: "margin-top:8px"}, "La saisie de cette période est fermée : demandez au titulaire de la classe de la rouvrir pour pouvoir saisir ou corriger.") : null,
    d.maintenant_complet ? h("div", {class: "meta", style: "color:var(--vert);font-weight:600"}, "Toutes les notes de cette fiche sont maintenant saisies.")
      : d.manquantes_actuelles ? h("div", {class: "meta", style: "color:var(--rouge);font-weight:600"}, d.manquantes_actuelles + " note(s) encore manquante(s) (onglet Points).") : null,
    h("div", {class: "barre"}, rep, bt));
}
function carteHistorique(d) {
  return h("div", {class: "corr"},
    h("div", {class: "tete"}, h("b", {}, titreCorrection(d)), h("span", {class: "badge " + (d.statut === "TRAITEE" ? "p" : "n")}, d.statut_libelle)),
    h("div", {class: "meta"}, "Demande du " + d.date + " (" + d.par + ")" + (d.date_traitement ? " · " + d.statut_libelle.toLowerCase() + " le " + d.date_traitement : "")),
    h("p", {class: "motif"}, d.motif),
    d.reponse ? h("p", {class: "rep"}, "Votre réponse : " + d.reponse) : null);
}
function dessinerCorrections() {
  $("cor-info").textContent = COR.nb_ouvertes
    ? COR.nb_ouvertes + " demande(s) de la direction des études à traiter. Corrigez vos points dans l'onglet Points, puis revenez les marquer comme traitées."
    : "Aucune demande de la direction des études pour le moment.";
  $("cor-liste").replaceChildren(...COR.ouvertes.map(carteOuverte),
    COR.historique.length ? h("h3", {style: "margin:16px 0 8px;font-size:15px"}, "Demandes déjà traitées ou annulées") : null,
    ...COR.historique.map(carteHistorique));
}
function formatDate(d) { return [("0" + d.getDate()).slice(-2), ("0" + (d.getMonth() + 1)).slice(-2), d.getFullYear()].join("/"); }
function decalerJour(n) { const d = enDate($("s-jour").value) || new Date(); d.setDate(d.getDate() + n); $("s-jour").value = formatDate(d); charger(); }
$("b-jour-moins").addEventListener("click", () => decalerJour(-1));
$("b-jour-plus").addEventListener("click", () => decalerJour(1));
$("b-aujourdhui").addEventListener("click", () => { $("s-jour").value = aujourdhui(); histo = false; $("b-hist").textContent = "Présences du cours"; charger(); });
$("s-jour").addEventListener("change", () => { histo = false; $("b-hist").textContent = "Présences du cours"; charger(); });
$("b-hist").addEventListener("click", () => { histo = !histo; $("b-hist").textContent = histo ? "Retour au pointage" : "Présences du cours"; charger(); });
$("b-tous").addEventListener("click", async () => {
  if (!P) return;
  try { const r = await api("POST", "presence/tous", {cc: P.id_cc, date: $("s-jour").value}); await charger(); msg(r.faits ? r.faits + " élèves pointés présents." : "Tous les élèves étaient déjà pointés.", true); }
  catch (e) { msg(e.message); }
});
function compterPresence() {
  const p = P.eleves.filter(e => e.statut === "P").length, a = P.eleves.filter(e => e.statut === "A").length;
  P.presents = p; P.absents = a; P.non_pointes = P.eleves.length - p - a;
  return "Présents : " + p + "   |   Absents : " + a + "   |   Pas encore pointés : " + P.non_pointes;
}
function dessinerPresence() {
  const edit = P.modifiable;
  $("b-tous").disabled = !edit;
  const resume = h("span", null, compterPresence());
  const lignes = P.eleves.map((e, i) => {
    const bp = h("button", {class: "pt p" + (e.statut === "P" ? " on" : ""), disabled: !edit, "aria-label": e.nom_complet + " présent"}, "Présent");
    const ba = h("button", {class: "pt a" + (e.statut === "A" ? " on" : ""), disabled: !edit, "aria-label": e.nom_complet + " absent"}, "Absent");
    const pointer = async (valeur) => {
      const nouveau = e.statut === valeur ? "" : valeur;               // toucher le bouton actif retire le pointage
      try {
        await api("POST", "presence/marquer", {cc: P.id_cc, date: $("s-jour").value, matricule: e.matricule, statut: nouveau});
        e.statut = nouveau; bp.classList.toggle("on", nouveau === "P"); ba.classList.toggle("on", nouveau === "A");
        resume.textContent = compterPresence(); msg("");
      } catch (x) { msg(x.message); }
    };
    bp.addEventListener("click", () => pointer("P")); ba.addEventListener("click", () => pointer("A"));
    return h("tr", null, h("td", {class: "num"}, i + 1), h("td", {class: "nom", title: e.nom_complet}, e.nom_complet), h("td", null, bp, " ", ba));
  });
  const corps = P.eleves.length ? h("div", {class: "tableau"}, h("table", null, h("thead", null, h("tr", null, h("th", {class: "n"}, "N°"), h("th", {class: "nom"}, "Élève"), h("th", null, "Présence à votre cours"))), h("tbody", null, lignes)))
                                : h("div", {class: "carte vide"}, "Aucun élève n'est inscrit dans cette classe.");
  $("zone").replaceChildren(h("div", {style: "margin:0 2px 8px;font-weight:600"}, P.cours + " - " + P.classe + (P.option ? " - " + P.option : "") + "  |  " + P.date), h("div", {style: "margin:0 2px 8px;color:var(--gris)"}, resume), corps);
  $("legende").replaceChildren(h("p", null, h("b", null, "Présence : "), "touchez ", h("b", null, "Présent"), " ou ", h("b", null, "Absent"), " pour chaque élève (toucher de nouveau retire le pointage). ", h("b", null, "Tous présents"), " pointe d'un coup les élèves pas encore pointés : touchez ensuite ", h("b", null, "Absent"), " pour ceux qui manquent."),
    h("p", null, "Vous pointez seulement vos heures de cours. Le titulaire de la classe ne voit pas ces présences : elles sont consultées par le Directeur de discipline et la Directrice des études."));
}
async function chargerHistorique(cc) {
  const H = await api("GET", "presence/historique", {cc});
  const tete = h("tr", null, h("th", {class: "n"}, "N°"), h("th", {class: "nom"}, "Élève"), h("th", null, "Prés."), h("th", null, "Abs."), h("th", null, "Taux"), ...H.jours.map(j => h("th", null, j.slice(0, 5))));
  const lignes = H.eleves.map((e, i) => h("tr", null, h("td", {class: "num"}, i + 1), h("td", {class: "nom", title: e.nom_complet}, e.nom_complet), h("td", null, e.presences), h("td", null, e.absences), h("td", null, e.taux == null ? "-" : fmt(e.taux) + " %"),
    ...e.codes.map(c => h("td", {class: c === "P" ? "c-p" : c === "A" ? "c-a" : ""}, c === "P" ? "P" : c === "A" ? "A" : "-"))));
  $("zone").replaceChildren(h("div", {style: "margin:0 2px 8px;font-weight:600"}, H.cours + " - " + H.classe + "  |  présences de l'année " + H.annee),
    H.jours.length ? h("div", {class: "tableau"}, h("table", null, h("thead", null, tete), h("tbody", null, lignes))) : h("div", {class: "carte vide"}, "Aucune présence n'a encore été pointée pour ce cours."));
  $("legende").replaceChildren(h("p", null, h("b", null, "P"), " = présent  ", h("b", null, "A"), " = absent  ", h("b", null, "-"), " = pas pointé  |  Prés. / Abs. = nombre de cours pointés, Taux = présences sur cours pointés. Les jours les plus récents sont à gauche (60 jours pointés au plus)."));
}

// ---------------------------------------------------------------- démarrage
(async () => {
  if (jeton) { try { await demarrer(null, true); return; } catch (e) { deconnecterLocal(""); } }
  montrer("vue-login");
})();

// ---------------------------------------------------------------- installation sur l'écran d'accueil (PWA)
(function () {
  let invitation = null;
  const carte = $("carte-installer");
  if (!carte) return;
  const dejaInstallee = () => (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true;
  function maj() {
    if (dejaInstallee()) { carte.hidden = true; return; }
    const ua = navigator.userAgent || "", ios = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    const b = $("b-installer"), aide = $("aide-installer"), texte = $("installer-texte");
    b.hidden = true; aide.hidden = true; aide.textContent = "";
    const etapes = liste => { liste.forEach(t => { const li = document.createElement("li"); li.textContent = t; aide.appendChild(li); }); aide.hidden = false; };
    if (invitation) b.hidden = false;
    else if (ios) {
      texte.textContent = "Sur iPhone et iPad, l'installation se fait depuis Safari :";
      etapes(["Ouvrez cette page dans Safari.", "Touchez le bouton Partager (carré avec une flèche).", "Choisissez « Sur l'écran d'accueil », puis « Ajouter »."]);
    } else {
      texte.textContent = "Installez l'application depuis le menu du navigateur :";
      etapes(["Ouvrez le menu du navigateur (trois points en haut à droite).", "Choisissez « Installer l'application » ou « Ajouter à l'écran d'accueil ».", "Confirmez : l'icône GESTSCO apparaît sur l'écran d'accueil."]);
    }
    carte.hidden = false;
  }
  window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); invitation = e; maj(); });
  window.addEventListener("appinstalled", () => { invitation = null; carte.hidden = true; });
  $("b-installer").addEventListener("click", async () => {
    if (!invitation) return;
    invitation.prompt();
    try { await invitation.userChoice; } catch (e) {}
    invitation = null; maj();
  });
  maj();
  if ("serviceWorker" in navigator) window.addEventListener("load", () => { navigator.serviceWorker.register("/professeur-sw.js", {scope: "/professeur"}).catch(() => {}); });
})();
</script>
</body>
</html>
"""


# Service worker de l'espace professeurs (servi par /professeur-sw.js). Il rend l'application installable et garde la page elle-même
# pour l'ouvrir hors connexion. Il ne touche JAMAIS à /api (notes, élèves, sessions) : seuls la page (sans donnée personnelle),
# le manifeste et les icônes sont gardés. Réseau d'abord : une mise à jour du logiciel est prise dès que l'appareil est connecté.
SERVICE_WORKER = r"""const VERSION = "prof-__VERSION__";
const COQUILLE = ["/professeur", "/professeur/manifest.webmanifest", "/assets/gestsco_192.png", "/assets/gestsco_512.png",
                  "/assets/gestsco_maskable_192.png", "/assets/gestsco_maskable_512.png", "/assets/gestsco_180.png", "/assets/gestisc_96.png"];
const HORS_LIGNE = "<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" +
  "<title>Hors connexion</title><body style='font:18px system-ui,sans-serif;background:#0A1E45;color:#fff;text-align:center;padding:18vh 24px'>" +
  "<h1 style='font-size:22px'>Pas de connexion</h1><p>La saisie des points a besoin du réseau. Vérifiez le Wi-Fi ou les données mobiles, puis rouvrez l'application.</p></body></html>";

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(VERSION).then(function (c) { return Promise.all(COQUILLE.map(function (u) { return c.add(u).catch(function () {}); })); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (noms) { return Promise.all(noms.filter(function (n) { return n.indexOf("prof-") === 0 && n !== VERSION; }).map(function (n) { return caches.delete(n); })); }).then(function () { return self.clients.claim(); }));
});
self.addEventListener("fetch", function (e) {
  var r = e.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== location.origin) return;
  if (r.mode === "navigate" && (u.pathname === "/professeur" || u.pathname === "/professeur/")) {
    e.respondWith(fetch(r).then(function (rep) {
      if (rep.ok) { var copie = rep.clone(); caches.open(VERSION).then(function (c) { c.put("/professeur", copie); }); }
      return rep;
    }).catch(function () {
      return caches.match("/professeur").then(function (c) { return c || new Response(HORS_LIGNE, {headers: {"Content-Type": "text/html; charset=utf-8"}}); });
    }));
    return;
  }
  if (COQUILLE.indexOf(u.pathname) >= 0) {
    e.respondWith(caches.match(r).then(function (c) { return c || fetch(r); }));
  }
});
"""
