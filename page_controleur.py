"""Page de l'application mobile de contrôle (une seule page, pensée pour le téléphone ; installable sur l'écran d'accueil).
Servie par web_controle_mobile.py. Le texte venant du serveur est toujours inséré avec textContent (jamais en HTML) :
aucune injection possible. Le jeton de session reste dans sessionStorage (effacé à la fermeture de l'onglet)."""

PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0A1E45">
<link rel="manifest" href="/controleur/manifest.webmanifest">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Contrôle">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/assets/controleur_180.png">
<link rel="icon" type="image/png" href="/assets/controleur_192.png">
<title>Contrôle numérique</title>
<style>
:root{--nuit:#0A1E45;--bleu:#1D4ED8;--fond:#F4F6FB;--carte:#fff;--bord:#D7DEEE;--texte:#0F1B3D;--gris:#5B6785;--vert:#1E8E5A;--rouge:#C0392B;--orange:#D9822B}
@media (prefers-color-scheme:dark){:root{--fond:#0B1226;--carte:#131D3A;--bord:#2A3860;--texte:#E8EDFB;--gris:#9AA8CF;--nuit:#060D20}}
*{box-sizing:border-box}
html,body{margin:0;background:var(--fond);color:var(--texte);font:16px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
[hidden]{display:none!important}
header{background:var(--nuit);color:#fff;padding:10px 14px;padding-top:calc(10px + env(safe-area-inset-top));display:flex;align-items:center;gap:10px;position:sticky;top:0;z-index:20}
header .titre{font-weight:700;flex:1;min-width:0}
header .titre small{display:block;font-weight:400;opacity:.8;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button,input{font:inherit;color:inherit}
.bouton{border:0;border-radius:10px;padding:12px 16px;font-weight:700;cursor:pointer;background:var(--bleu);color:#fff;min-height:48px;width:100%}
.bouton.sec{background:transparent;color:var(--texte);border:1px solid var(--bord)}
header .bouton{background:#183268;min-height:38px;padding:6px 12px;width:auto;font-size:14px}
.page{max-width:520px;margin:0 auto;padding:12px 12px calc(40px + env(safe-area-inset-bottom))}
.carte{background:var(--carte);border:1px solid var(--bord);border-radius:14px;padding:14px;margin-bottom:12px}
.centre{margin-top:6vh}
h1{font-size:20px;margin:0 0 4px}
.sous{color:var(--gris);font-size:14px;margin:0 0 6px}
label{display:block;font-size:13px;font-weight:600;color:var(--gris);margin:12px 0 4px}
input[type=text],input[type=password]{width:100%;padding:12px;border:1px solid var(--bord);border-radius:10px;background:var(--carte);min-height:48px}
.message{margin:10px 0 0;font-weight:600;min-height:1.2em;white-space:pre-line}
.message.err{color:var(--rouge)}.message.ok{color:var(--vert)}
.choix{display:flex;flex-direction:column;gap:8px;margin:10px 0 14px}
.choix button{text-align:left;border:2px solid var(--bord);background:var(--carte);border-radius:12px;padding:14px;font-weight:700;min-height:52px;cursor:pointer}
.choix button.actif{border-color:var(--bleu);background:rgba(29,78,216,.12)}
#zone-video{position:relative;border-radius:14px;overflow:hidden;background:#000;margin-bottom:10px}
#video{width:100%;max-height:44vh;object-fit:cover;display:block}
#cadre{position:absolute;inset:0;margin:auto;width:58%;aspect-ratio:1;border:3px solid rgba(255,255,255,.9);border-radius:16px;box-shadow:0 0 0 999px rgba(0,0,0,.35);pointer-events:none}
.ligne{display:flex;gap:8px}.ligne input{flex:1}.ligne .bouton{width:auto;min-width:110px}
.bandeau{border-radius:14px 14px 0 0;padding:16px;text-align:center;color:#fff;font-weight:800;font-size:28px;letter-spacing:.5px}
.bandeau small{display:block;font-weight:600;font-size:14px;opacity:.95;letter-spacing:0;margin-top:2px}
.bandeau.ordre{background:var(--vert)}.bandeau.impaye{background:var(--rouge)}.bandeau.autre{background:var(--orange)}.bandeau.erreur{background:#4B5878}
.fiche{border:1px solid var(--bord);border-top:0;border-radius:0 0 14px 14px;background:var(--carte);padding:14px;margin-bottom:12px}
.id{display:flex;gap:12px;align-items:flex-start}
#photo{width:96px;height:128px;object-fit:cover;border-radius:10px;border:1px solid var(--bord);background:var(--fond);flex:none}
.sans-photo{width:96px;height:128px;border-radius:10px;border:1px dashed var(--bord);color:var(--gris);font-size:12px;display:flex;align-items:center;justify-content:center;text-align:center;padding:6px;flex:none}
.id .nom{font-weight:800;font-size:18px;margin:0 0 4px;overflow-wrap:anywhere}
.id p{margin:2px 0;color:var(--gris);font-size:14px}
.alerte{margin-top:10px;padding:8px 10px;border-radius:8px;background:rgba(217,130,43,.18);font-weight:600;font-size:14px}
.frais{margin-top:12px;border-top:1px solid var(--bord)}
.frais .l{padding:8px 0;border-bottom:1px solid var(--bord);display:flex;justify-content:space-between;gap:8px;font-size:14px}
.frais .l b{overflow-wrap:anywhere}.frais .l span{color:var(--gris);text-align:right}
.frais .l.reste span{color:var(--rouge);font-weight:700}
.pied{font-size:12px;color:var(--gris);margin-top:10px}
.installer{border-color:var(--bleu)}
.installer h2{font-size:16px;margin:0 0 4px}
.installer ol{margin:6px 0 0;padding-left:20px;font-size:14px;color:var(--gris)}
</style>
</head>
<body>
<header>
  <div class="titre">Contrôle numérique<small id="sous-titre">__ECOLE__</small></div>
  <button class="bouton" id="b-deconnexion" hidden>Déconnexion</button>
</header>
<main class="page">

<section id="ecran-connexion" class="carte centre" hidden>
  <h1>Contrôle des frais</h1>
  <p class="sous">Connectez-vous avec votre identifiant et votre mot de passe.</p>
  <label for="login">Identifiant</label>
  <input type="text" id="login" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false">
  <label for="mdp">Mot de passe</label>
  <input type="password" id="mdp" autocomplete="current-password">
  <div class="message err" id="msg-connexion" role="alert"></div>
  <p style="margin-top:12px"><button class="bouton" id="b-connexion">Se connecter</button></p>
</section>

<section id="carte-installer" class="carte installer" hidden>
  <h2>Installer l'application</h2>
  <p class="sous" id="installer-texte">Ajoutez « Contrôle numérique » à l'écran d'accueil du téléphone : elle s'ouvre en plein écran, comme une application.</p>
  <button class="bouton" id="b-installer" hidden>Installer sur ce téléphone</button>
  <ol id="aide-installer" hidden></ol>
</section>

<section id="ecran-mdp" class="carte centre" hidden>
  <h1>Nouveau mot de passe</h1>
  <p class="sous">Vous devez changer votre mot de passe avant de commencer.</p>
  <label for="mdp-ancien">Mot de passe actuel</label>
  <input type="password" id="mdp-ancien" autocomplete="current-password">
  <label for="mdp-nouveau">Nouveau mot de passe</label>
  <input type="password" id="mdp-nouveau" autocomplete="new-password">
  <label for="mdp-conf">Confirmer le nouveau mot de passe</label>
  <input type="password" id="mdp-conf" autocomplete="new-password">
  <div class="message err" id="msg-mdp" role="alert"></div>
  <p style="margin-top:12px"><button class="bouton" id="b-mdp">Enregistrer</button></p>
</section>

<section id="ecran-frais" hidden>
  <div class="carte">
    <h1>Quel frais contrôler ?</h1>
    <p class="sous">Choisissez un type de frais, ou tous les frais.</p>
    <div class="choix" id="liste-frais"></div>
    <div class="message err" id="msg-frais" role="alert"></div>
    <button class="bouton" id="b-commencer" disabled>Commencer le contrôle</button>
  </div>
</section>

<section id="ecran-scan" hidden>
  <div class="carte" style="padding:10px 14px;display:flex;align-items:center;gap:10px">
    <div style="flex:1;min-width:0"><div class="sous" style="margin:0">Frais contrôlé</div><b id="frais-actif" style="overflow-wrap:anywhere"></b></div>
    <button class="bouton sec" id="b-changer" style="width:auto;min-height:40px;padding:8px 12px">Changer</button>
  </div>
  <div id="zone-scan">
    <div id="zone-video" hidden><video id="video" playsinline muted></video><div id="cadre"></div></div>
    <p class="sous" id="note-camera"></p>
    <form class="ligne" id="form-manuel" autocomplete="off">
      <input type="text" id="matricule" placeholder="Matricule (ex. 0001/26)" autocapitalize="characters" autocorrect="off" spellcheck="false" aria-label="Matricule de l'élève">
      <button class="bouton" type="submit">Contrôler</button>
    </form>
  </div>
  <div id="resultat" hidden>
    <div class="bandeau" id="bandeau"><span id="statut"></span><small id="motif"></small></div>
    <div class="fiche">
      <div class="id">
        <img id="photo" alt="Photo de l'élève" hidden>
        <div class="sans-photo" id="sans-photo" hidden>Pas de photo enregistrée</div>
        <div>
          <p class="nom" id="r-nom"></p>
          <p id="r-matricule"></p><p id="r-classe"></p><p id="r-ident"></p>
        </div>
      </div>
      <div class="alerte" id="r-alerte" hidden></div>
      <div class="frais" id="r-frais"></div>
      <p class="pied" id="r-pied"></p>
    </div>
    <button class="bouton" id="b-suivant">Contrôle suivant</button>
  </div>
</section>
</main>

<script>
"use strict";
var jeton = "", fraisCode = "", fraisLibelle = "", flux = null, detecteur = null, minuteur = null;
var occupe = false, pause = false, dernier = {code: "", t: 0}, serveurLit = true;
try { jeton = sessionStorage.getItem("ctrl_jeton") || ""; fraisCode = sessionStorage.getItem("ctrl_frais") || ""; fraisLibelle = sessionStorage.getItem("ctrl_frais_lib") || ""; } catch (e) {}

function el(id) { return document.getElementById(id); }
function montrer(nom) {
  ["connexion", "mdp", "frais", "scan"].forEach(function (n) { el("ecran-" + n).hidden = (n !== nom); });
  el("b-deconnexion").hidden = (nom === "connexion");
  majInstaller(nom === "connexion");
  if (nom !== "scan") arreterCamera();
}

// ---------------------------------------------------------------- installation sur l'écran d'accueil (PWA)
var invitation = null;
function dejaInstallee() { return (window.matchMedia && matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true; }
function majInstaller(surConnexion) {
  var c = el("carte-installer"); if (!c) return;
  if (!surConnexion || dejaInstallee()) { c.hidden = true; return; }
  var ua = navigator.userAgent || "", ios = /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  var b = el("b-installer"), aide = el("aide-installer"), texte = el("installer-texte");
  b.hidden = true; aide.hidden = true; aide.textContent = "";
  function etapes(liste) { liste.forEach(function (t) { var li = document.createElement("li"); li.textContent = t; aide.appendChild(li); }); aide.hidden = false; }
  if (invitation) { b.hidden = false; }
  else if (ios) {
    texte.textContent = "Sur iPhone, l'installation se fait depuis Safari :";
    etapes(["Ouvrez cette page dans Safari (pas dans une autre application).", "Touchez le bouton Partager (carré avec une flèche).", "Choisissez « Sur l'écran d'accueil », puis « Ajouter »."]);
  } else {
    texte.textContent = "Installez l'application depuis le menu du navigateur :";
    etapes(["Ouvrez le menu du navigateur (trois points ⋮ en haut à droite).", "Choisissez « Installer l'application » ou « Ajouter à l'écran d'accueil ».", "Confirmez : l'icône apparaît sur l'écran d'accueil."]);
  }
  c.hidden = false;
}
window.addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); invitation = e; majInstaller(!el("ecran-connexion").hidden); });
window.addEventListener("appinstalled", function () { invitation = null; el("carte-installer").hidden = true; });
el("b-installer").addEventListener("click", async function () {
  if (!invitation) return;
  invitation.prompt();
  try { await invitation.userChoice; } catch (e) {}
  invitation = null; majInstaller(!el("ecran-connexion").hidden);
});
if ("serviceWorker" in navigator) { window.addEventListener("load", function () { navigator.serviceWorker.register("/controleur-sw.js", {scope: "/controleur"}).catch(function () {}); }); }
function sauver() { try { jeton ? sessionStorage.setItem("ctrl_jeton", jeton) : sessionStorage.removeItem("ctrl_jeton"); sessionStorage.setItem("ctrl_frais", fraisCode); sessionStorage.setItem("ctrl_frais_lib", fraisLibelle); } catch (e) {} }

async function api(chemin, opts) {
  opts = opts || {};
  var h = {}, corps;
  if (jeton) h["Authorization"] = "Bearer " + jeton;
  if (opts.binaire) { h["Content-Type"] = "image/jpeg"; corps = opts.binaire; }
  else if (opts.json) { h["Content-Type"] = "application/json"; corps = JSON.stringify(opts.json); }
  var r;
  try { r = await fetch("/mobile/api/" + chemin, {method: corps !== undefined ? "POST" : "GET", headers: h, body: corps}); }
  catch (e) { throw {erreur: "Pas de connexion au serveur. Vérifiez votre réseau.", reseau: true}; }
  var d = {};
  try { d = await r.json(); } catch (e) {}
  if (r.status === 401) { sortir(d.erreur || "Session expirée : reconnectez-vous."); throw {erreur: d.erreur, session: true}; }
  if (r.status === 403 && d.coupee) { sortir(d.erreur); throw {erreur: d.erreur, coupee: true}; }
  if (!r.ok) throw {erreur: d.erreur || "Erreur du serveur."};
  return d;
}

function sortir(message) {
  jeton = ""; sauver(); arreterCamera();
  el("mdp").value = ""; el("msg-connexion").textContent = message || "";
  montrer("connexion");
}

// ---------------------------------------------------------------- connexion
async function seConnecter() {
  var m = el("msg-connexion"); m.textContent = "";
  try {
    var d = await api("connexion", {json: {login: el("login").value, mdp: el("mdp").value}});
    jeton = d.jeton; el("mdp").value = ""; sauver();
    el("sous-titre").textContent = d.nom + " · " + d.poste;
    if (d.doit_changer_mdp) { montrer("mdp"); return; }
    await chargerFrais();
  } catch (e) { if (!e.session && !e.coupee) m.textContent = e.erreur || "Connexion impossible."; }
}
async function changerMdp() {
  var m = el("msg-mdp"); m.textContent = "";
  try {
    await api("mot-de-passe", {json: {ancien: el("mdp-ancien").value, nouveau: el("mdp-nouveau").value, confirmation: el("mdp-conf").value}});
    el("mdp-ancien").value = el("mdp-nouveau").value = el("mdp-conf").value = "";
    await chargerFrais();
  } catch (e) { if (!e.session && !e.coupee) m.textContent = e.erreur || "Changement impossible."; }
}
async function deconnecter() {
  try { await api("deconnexion", {json: {}}); } catch (e) {}
  sortir("");
}

// ---------------------------------------------------------------- choix du frais
async function chargerFrais() {
  var d = await api("frais");
  var zone = el("liste-frais"); zone.textContent = "";
  var options = [["TOUS", "Tous les frais"]].concat(d.frais);
  options.forEach(function (o) {
    var b = document.createElement("button"); b.type = "button"; b.textContent = o[1];
    if (o[0] === fraisCode) b.className = "actif";
    b.addEventListener("click", function () {
      fraisCode = o[0]; fraisLibelle = o[1]; sauver();
      Array.prototype.forEach.call(zone.children, function (x) { x.className = ""; }); b.className = "actif";
      el("b-commencer").disabled = false;
    });
    zone.appendChild(b);
  });
  if (!options.some(function (o) { return o[0] === fraisCode; })) { fraisCode = ""; fraisLibelle = ""; }
  el("b-commencer").disabled = !fraisCode;
  el("msg-frais").textContent = "";
  montrer("frais");
}
function commencer() {
  if (!fraisCode) return;
  el("frais-actif").textContent = fraisLibelle;
  el("resultat").hidden = true; el("zone-scan").hidden = false; el("matricule").value = "";
  pause = false; dernier = {code: "", t: 0};
  montrer("scan"); demarrerCamera();
}

// ---------------------------------------------------------------- caméra et lecture du QR
function arreterCamera() {
  if (minuteur) { clearInterval(minuteur); minuteur = null; }
  if (flux) { flux.getTracks().forEach(function (t) { t.stop(); }); flux = null; }
  var z = el("zone-video"); if (z) z.hidden = true;
}
async function demarrerCamera() {
  arreterCamera();
  var note = el("note-camera"); note.textContent = "";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { note.textContent = "Caméra indisponible (connexion HTTPS requise) : saisissez le matricule."; return; }
  try { flux = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: "environment"}, width: {ideal: 1280}}, audio: false}); }
  catch (e) { note.textContent = "Caméra non autorisée : autorisez-la dans le navigateur, ou saisissez le matricule."; return; }
  var v = el("video"); v.srcObject = flux;
  try { await v.play(); } catch (e) {}
  el("zone-video").hidden = false;
  note.textContent = "Placez le QR de la carte dans le cadre, ou saisissez le matricule.";
  detecteur = null;
  if ("BarcodeDetector" in window) { try { detecteur = new BarcodeDetector({formats: ["qr_code"]}); } catch (e) { detecteur = null; } }
  minuteur = setInterval(lire, detecteur ? 250 : 1300);
}
function lireParServeur(v) {
  return new Promise(function (resolve, reject) {
    var l = Math.min(640, v.videoWidth), h = Math.round(v.videoHeight * l / v.videoWidth);
    var c = document.createElement("canvas"); c.width = l; c.height = h;
    c.getContext("2d").drawImage(v, 0, 0, l, h);
    c.toBlob(function (blob) {
      if (!blob) { resolve(""); return; }
      api("decoder", {binaire: blob}).then(function (d) {
        if (d.indisponible) { serveurLit = false; el("note-camera").textContent = "La lecture du QR n'est pas disponible sur ce téléphone : saisissez le matricule."; }
        resolve(d.code || "");
      }, reject);
    }, "image/jpeg", 0.6);
  });
}
async function lire() {
  if (pause || occupe) return;
  var v = el("video"); if (!v.videoWidth) return;
  if (!detecteur && !serveurLit) return;
  occupe = true;
  try {
    var code = "";
    if (detecteur) { var r = await detecteur.detect(v); if (r.length) code = r[0].rawValue; }
    else code = await lireParServeur(v);
    if (code && !(code === dernier.code && Date.now() - dernier.t < 4000)) { dernier = {code: code, t: Date.now()}; await controler(code); }
  } catch (e) {} finally { occupe = false; }
}

// ---------------------------------------------------------------- contrôle et résultat
function ligne(parent, classe, gauche, droite) {
  var d = document.createElement("div"); d.className = "l " + classe;
  var a = document.createElement("b"); a.textContent = gauche;
  var b = document.createElement("span"); b.textContent = droite;
  d.appendChild(a); d.appendChild(b); parent.appendChild(d);
}
function afficherResultat(r) {
  var b = el("bandeau");
  b.className = "bandeau " + (r.couleur || "autre");
  el("statut").textContent = r.statut; el("motif").textContent = r.motif;
  el("r-nom").textContent = r.nom_complet;
  el("r-matricule").textContent = "Matricule : " + r.matricule;
  el("r-classe").textContent = r.classe ? ("Classe : " + r.classe + (r.option ? " · " + r.option : "")) : "Pas d'inscription en " + r.annee;
  el("r-ident").textContent = r.identification === "QR" ? "Carte lue (QR valide)" : "Matricule saisi : comparez la photo avec la personne";
  var p = el("photo"), sp = el("sans-photo");
  if (r.photo) { p.src = r.photo; p.hidden = false; sp.hidden = true; } else { p.hidden = true; p.removeAttribute("src"); sp.hidden = false; }
  var al = el("r-alerte");
  if (!r.actif) { al.textContent = "Le compte de cet élève est désactivé."; al.hidden = false; } else al.hidden = true;
  var f = el("r-frais"); f.textContent = "";
  r.lignes.forEach(function (l) {
    ligne(f, "", l.frais, l.statut);
    ligne(f, "", "Dû / payé", l.du + " / " + l.paye);
    if (l.reste_positif) ligne(f, "reste", "Reste à payer", l.reste);
  });
  r.dettes.forEach(function (t) { ligne(f, "reste", "Dette", t); });
  if (r.sans_frais) ligne(f, "", "Aucun frais défini pour cette classe", "");
  el("r-pied").textContent = "Frais contrôlé : " + r.frais_choisi + " · année " + r.annee;
  el("resultat").hidden = false; el("zone-scan").hidden = true;
  arreterCamera();
  if (navigator.vibrate) navigator.vibrate(r.statut === "EN ORDRE" ? 80 : [200, 100, 200]);
  window.scrollTo(0, 0);
}
function afficherErreur(texte) {
  el("bandeau").className = "bandeau erreur";
  el("statut").textContent = "Contrôle impossible"; el("motif").textContent = texte;
  el("r-nom").textContent = ""; el("r-matricule").textContent = ""; el("r-classe").textContent = ""; el("r-ident").textContent = "";
  el("photo").hidden = true; el("photo").removeAttribute("src"); el("sans-photo").hidden = true;
  el("r-alerte").hidden = true; el("r-frais").textContent = ""; el("r-pied").textContent = "";
  el("resultat").hidden = false; el("zone-scan").hidden = true;
  arreterCamera();
  if (navigator.vibrate) navigator.vibrate([300]);
}
async function controler(code) {
  pause = true;
  try { afficherResultat(await api("controle", {json: {code: code, frais: fraisCode}})); }
  catch (e) { if (!e.session && !e.coupee) afficherErreur(e.erreur || "Contrôle impossible."); }
}
function suivant() {
  dernier.t = Date.now();
  el("resultat").hidden = true; el("zone-scan").hidden = false; el("matricule").value = "";
  pause = false; demarrerCamera();
}

el("b-connexion").addEventListener("click", seConnecter);
el("mdp").addEventListener("keydown", function (e) { if (e.key === "Enter") seConnecter(); });
el("b-mdp").addEventListener("click", changerMdp);
el("b-deconnexion").addEventListener("click", deconnecter);
el("b-commencer").addEventListener("click", commencer);
el("b-changer").addEventListener("click", function () { chargerFrais().catch(function () {}); });
el("b-suivant").addEventListener("click", suivant);
el("form-manuel").addEventListener("submit", function (e) {
  e.preventDefault();
  var v = el("matricule").value.trim();
  if (v) controler(v);
});

if (jeton) { chargerFrais().catch(function () { montrer("connexion"); }); } else montrer("connexion");
</script>
</body>
</html>
"""

# Service worker (servi par /controleur-sw.js). Rôle : rendre l'application installable et garder la page elle-même pour l'ouvrir hors
# connexion. Il ne met JAMAIS en cache /mobile/api (données d'élèves, sessions) : seules la page (sans donnée personnelle), le manifeste
# et les icônes sont gardés. Réseau d'abord : une mise à jour du logiciel est prise dès que le téléphone est connecté.
SERVICE_WORKER = r"""const VERSION = "ctrl-__VERSION__";
const COQUILLE = ["/controleur", "/controleur/manifest.webmanifest", "/assets/controleur_192.png", "/assets/controleur_512.png",
                  "/assets/controleur_maskable_192.png", "/assets/controleur_maskable_512.png", "/assets/controleur_180.png"];
const HORS_LIGNE = "<!doctype html><html lang='fr'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>" +
  "<title>Hors connexion</title><body style='font:18px system-ui,sans-serif;background:#0A1E45;color:#fff;text-align:center;padding:18vh 24px'>" +
  "<h1 style='font-size:22px'>Pas de connexion</h1><p>Le contrôle a besoin du réseau. Vérifiez le Wi-Fi ou les données mobiles, puis rouvrez l'application.</p></body></html>";

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(VERSION).then(function (c) { return Promise.all(COQUILLE.map(function (u) { return c.add(u).catch(function () {}); })); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (noms) { return Promise.all(noms.filter(function (n) { return n.indexOf("ctrl-") === 0 && n !== VERSION; }).map(function (n) { return caches.delete(n); })); }).then(function () { return self.clients.claim(); }));
});
self.addEventListener("fetch", function (e) {
  var r = e.request, u = new URL(r.url);
  if (r.method !== "GET" || u.origin !== location.origin) return;
  if (r.mode === "navigate" && (u.pathname === "/controleur" || u.pathname === "/controleur/")) {
    e.respondWith(fetch(r).then(function (rep) {
      if (rep.ok) { var copie = rep.clone(); caches.open(VERSION).then(function (c) { c.put("/controleur", copie); }); }
      return rep;
    }).catch(function () {
      return caches.match("/controleur").then(function (c) { return c || new Response(HORS_LIGNE, {headers: {"Content-Type": "text/html; charset=utf-8"}}); });
    }));
    return;
  }
  if (COQUILLE.indexOf(u.pathname) >= 0) {
    e.respondWith(caches.match(r).then(function (c) { return c || fetch(r); }));
  }
});
"""
