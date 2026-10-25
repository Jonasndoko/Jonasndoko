"""Espace parents en ligne (v0.59) : une seule page web (/parents), sans installation, qui utilise l'API /parent/api/... (web_parents.py).

Le parent y entre avec le code du reçu, crée son compte, puis suit ses enfants : frais, présences, conduite, résultats.
Sécurité côté page : le jeton de session est gardé dans sessionStorage (effacé à la fermeture de l'onglet), jamais dans un cookie ;
tout texte venant du serveur est inséré avec textContent (jamais innerHTML) ; déconnexion automatique après 15 min sans action ;
texte non sélectionnable et impression désactivée (limite honnête : on ne peut pas empêcher une capture d'écran sur un navigateur).
"""

PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Espace parents - __ECOLE__</title>
<style>
 :root{--bleu:#1d4ed8;--fond:#f3f5fa;--texte:#14213d;--gris:#5b647a;--bord:#d6dbea;--ok:#15803d;--ko:#b91c1c;--att:#b45309}
 *{box-sizing:border-box}
 body{margin:0;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:var(--fond);color:var(--texte);-webkit-user-select:none;user-select:none}
 input{-webkit-user-select:text;user-select:text}
 header{background:var(--bleu);color:#fff;padding:12px 16px;display:flex;align-items:center;gap:10px}
 header h1{font-size:1.05rem;margin:0;flex:1} header small{display:block;font-weight:400;opacity:.85;font-size:.75rem}
 header button{background:rgba(255,255,255,.18);color:#fff;border:0;border-radius:8px;padding:8px 12px;font-size:.85rem;cursor:pointer}
 main{max-width:820px;margin:0 auto;padding:16px}
 .carte{background:#fff;border:1px solid var(--bord);border-radius:14px;padding:18px;margin-bottom:14px}
 h2{font-size:1.1rem;margin:0 0 10px} h3{font-size:.95rem;margin:16px 0 6px}
 label{display:block;font-size:.85rem;color:var(--gris);margin:12px 0 4px}
 input{width:100%;padding:12px;border:1px solid var(--bord);border-radius:10px;font-size:1rem}
 button.p{width:100%;margin-top:16px;padding:13px;border:0;border-radius:10px;background:var(--bleu);color:#fff;font-size:1rem;font-weight:600;cursor:pointer}
 button.s{background:none;border:0;color:var(--bleu);padding:10px 0;font-size:.9rem;cursor:pointer}
 button:disabled{opacity:.6}
 .err{background:#fef2f2;color:var(--ko);border:1px solid #fecaca;border-radius:10px;padding:10px;margin:12px 0;font-size:.9rem}
 .info{background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:10px;margin:12px 0;font-size:.9rem}
 .note{font-size:.8rem;color:var(--gris)}
 .enfant{display:block;width:100%;text-align:left;background:#fff;border:1px solid var(--bord);border-radius:14px;padding:16px;margin-bottom:10px;cursor:pointer;font-size:1rem}
 .enfant b{display:block} .enfant span{color:var(--gris);font-size:.88rem}
 .onglets{display:flex;gap:6px;overflow-x:auto;margin-bottom:12px}
 .onglets button{flex:1;white-space:nowrap;padding:10px 12px;border:1px solid var(--bord);background:#fff;border-radius:10px;font-size:.9rem;cursor:pointer}
 .onglets button.on{background:var(--bleu);color:#fff;border-color:var(--bleu)}
 .ligne{display:flex;justify-content:space-between;gap:10px;padding:9px 0;border-bottom:1px solid #eef0f6;font-size:.92rem}
 .ligne:last-child{border-bottom:0} .ligne .d{color:var(--gris);font-size:.8rem}
 .ok{color:var(--ok);font-weight:600} .ko{color:var(--ko);font-weight:600} .att{color:var(--att);font-weight:600}
 .stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px}
 .stat{flex:1;min-width:90px;background:var(--fond);border-radius:10px;padding:10px;text-align:center}
 .stat b{display:block;font-size:1.25rem}
 .defile{overflow-x:auto} table{border-collapse:collapse;width:100%;font-size:.85rem}
 th,td{border:1px solid var(--bord);padding:6px 8px;text-align:center;white-space:nowrap} th{background:var(--fond)} td.l,th.l{text-align:left}
 tr.tot td{font-weight:600;background:#f8fafc}
 .maj{font-size:.75rem;color:var(--gris);text-align:right;margin-top:6px}
 .enfant.notif{border-color:#fca5a5;background:#fef2f2} .enfant.notif b{color:var(--ko)}
 .badge{display:inline-block;font-size:.72rem;font-weight:700;border-radius:20px;padding:1px 9px;border:1px solid var(--bord);color:var(--gris);white-space:nowrap}
 .badge.nv{border-color:var(--ko);color:var(--ko)} .badge.an{border-color:var(--ko);color:var(--ko)} .badge.lu{border-color:var(--ok);color:var(--ok)}
 .lettre{border:1px solid var(--bord);border-radius:14px;padding:18px 20px;background:#fff;margin-bottom:14px}
 .lettre .ec{text-align:center;font-weight:700;margin:0} .lettre .sv{text-align:center;color:var(--gris);margin:2px 0 10px;font-size:.9rem}
 .lettre h2{text-align:center;font-size:1.2rem;margin:6px 0 12px;padding-bottom:12px;border-bottom:1px solid var(--bord)}
 .lettre p{margin:8px 0;line-height:1.45} .lettre .sg{color:var(--gris);font-size:.9rem;margin-top:14px}
 @media print{body{display:none!important}}
</style></head><body>
<header><h1 id="titre">Espace parents<small>__ECOLE__</small></h1><button id="btnOut" hidden>Déconnexion</button></header>
<main id="app"></main>
<script>
"use strict";
var RAFRAICHIR_S = 30, INACTIVITE_MIN = 15;
var app = document.getElementById("app"), btnOut = document.getElementById("btnOut");
var etat = {jeton: null, parent: null, enfants: [], code: "", timer: null, derniere: Date.now()};
try { etat.jeton = sessionStorage.getItem("jeton_parent"); } catch (e) {}

function h(tag, attrs) {
  var el = document.createElement(tag);
  for (var k in (attrs || {})) {
    if (k === "class") el.className = attrs[k];
    else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
    else el.setAttribute(k, attrs[k]);
  }
  (function ajouter(liste) {
    for (var i = 0; i < liste.length; i++) {
      var c = liste[i];
      if (c === null || c === undefined || c === false) continue;
      if (Array.isArray(c)) ajouter(c);
      else el.appendChild(typeof c === "object" ? c : document.createTextNode(String(c)));
    }
  })(Array.prototype.slice.call(arguments, 2));
  return el;
}
function vider(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
function montrer() { vider(app); for (var i = 0; i < arguments.length; i++) app.appendChild(arguments[i]); window.scrollTo(0, 0); }
function arreterTimer() { if (etat.timer) { clearInterval(etat.timer); etat.timer = null; } }

function sauverJeton(j) { etat.jeton = j; try { j ? sessionStorage.setItem("jeton_parent", j) : sessionStorage.removeItem("jeton_parent"); } catch (e) {} }

async function api(methode, chemin, corps) {
  var opts = {method: methode, headers: {"Content-Type": "application/json"}};
  if (etat.jeton) opts.headers["Authorization"] = "Bearer " + etat.jeton;
  if (corps) opts.body = JSON.stringify(corps);
  var r, d = {};
  try { r = await fetch("/parent/api" + chemin, opts); } catch (e) { throw {message: "Pas de connexion au serveur. Réessayez.", code: 0}; }
  try { d = await r.json(); } catch (e) {}
  if (!r.ok) {
    if (r.status === 401 && etat.jeton) { deconnecter(false, "Session expirée : reconnectez-vous."); }
    throw {message: d.erreur || "Erreur du serveur.", code: r.status, acces: d.acces};
  }
  return d;
}

function deconnecter(prevenir, message) {
  arreterTimer();
  if (prevenir && etat.jeton) { api("POST", "/deconnexion").catch(function () {}); }
  sauverJeton(null); etat.parent = null; etat.enfants = [];
  btnOut.hidden = true;
  accueil(message);
}
btnOut.addEventListener("click", function () { deconnecter(true); });
["click", "keydown", "touchstart"].forEach(function (ev) { document.addEventListener(ev, function () { etat.derniere = Date.now(); }, {passive: true}); });
setInterval(function () { if (etat.jeton && Date.now() - etat.derniere > INACTIVITE_MIN * 60000) deconnecter(true, "Déconnecté après " + INACTIVITE_MIN + " minutes d'inactivité."); }, 30000);

function champ(id, etiquette, type, extra) {
  var i = h("input", Object.assign({id: id, type: type || "text", autocomplete: "off"}, extra || {}));
  return [h("label", {"for": id}, etiquette), i];
}
function boite(texte, classe) { return texte ? h("div", {class: classe || "err", role: "alert"}, texte) : null; }
function surEnvoi(bouton, fonction) {
  return async function (ev) {
    if (ev) ev.preventDefault();
    bouton.disabled = true;
    try { await fonction(); } finally { bouton.disabled = false; }
  };
}

/* ---------------------------------------------------------------- accueil : connexion ou activation */
function accueil(message) {
  arreterTimer();
  var zoneC = h("div"), zoneA = h("div");
  var btnC = h("button", {class: "p", type: "submit"}, "Se connecter");
  var formC = h("form", {onsubmit: surEnvoi(btnC, async function () {
    vider(zoneC);
    try {
      var d = await api("POST", "/connexion", {identifiant: val("c_id"), mdp: val("c_mdp")});
      ouvertureSession(d);
    } catch (e) { zoneC.appendChild(boite(e.message)); }
  })}, champ("c_id", "Téléphone ou e-mail", "text", {autocomplete: "username"}), champ("c_mdp", "Mot de passe", "password", {autocomplete: "current-password"}), zoneC, btnC);

  var btnA = h("button", {class: "p", type: "submit"}, "Continuer");
  var formA = h("form", {onsubmit: surEnvoi(btnA, async function () {
    vider(zoneA);
    try {
      var code = val("a_code");
      var d = await api("POST", "/code/verifier", {code: code});
      etat.code = code;
      creationCompte(d);
    } catch (e) { zoneA.appendChild(boite(e.message)); }
  })}, champ("a_code", "Code d'accès (reçu de la caisse)", "text", {placeholder: "XXXX-XXXX-XXXX", autocapitalize: "characters"}), zoneA, btnA);

  montrer(
    h("div", {class: "carte"}, h("h2", {}, "Bienvenue"),
      h("p", {class: "note"}, "Suivez la situation de votre enfant : frais, présences, conduite et résultats."), boite(message, "info")),
    h("div", {class: "carte"}, h("h2", {}, "J'ai déjà un compte"), formC),
    h("div", {class: "carte"}, h("h2", {}, "Première visite"),
      h("p", {class: "note"}, "Payez à la caisse de l'école le frais du logiciel des parents : le reçu porte votre code d'accès. Un code = un enfant, il ne sert qu'une fois."),
      formA));
}
function val(id) { var e = document.getElementById(id); return e ? e.value.trim() : ""; }

function creationCompte(enfant) {
  var zone = h("div"), btn = h("button", {class: "p", type: "submit"}, "Créer mon compte");
  var form = h("form", {onsubmit: surEnvoi(btn, async function () {
    vider(zone);
    if (val("n_mdp") !== document.getElementById("n_mdp2").value.trim()) { zone.appendChild(boite("Les deux mots de passe ne sont pas identiques.")); return; }
    try {
      var d = await api("POST", "/inscription", {code: etat.code, nom: val("n_nom"), identifiant: val("n_id"), mdp: val("n_mdp")});
      etat.code = "";
      ouvertureSession(d);
    } catch (e) { zone.appendChild(boite(e.message)); }
  })}, champ("n_nom", "Votre nom complet"), champ("n_id", "Téléphone ou e-mail (servira à vous connecter)", "text", {autocomplete: "username"}),
     champ("n_mdp", "Mot de passe", "password", {autocomplete: "new-password"}), champ("n_mdp2", "Répétez le mot de passe", "password", {autocomplete: "new-password"}), zone, btn);
  montrer(h("div", {class: "carte"}, h("h2", {}, "Créer votre compte"),
    h("div", {class: "info"}, "Enfant : ", h("b", {}, enfant.prenom), " · ", enfant.classe || "classe non définie", " · ", enfant.annee || ""),
    form, h("button", {class: "s", onclick: function () { accueil(); }}, "← Retour")));
}

function ouvertureSession(d) {
  sauverJeton(d.jeton); etat.parent = d.parent; etat.enfants = d.enfants || [];
  etat.derniere = Date.now(); btnOut.hidden = false;
  listeEnfants();
}

/* ---------------------------------------------------------------- liste des enfants */
async function listeEnfants() {
  arreterTimer();
  try { etat.enfants = (await api("GET", "/enfants")).enfants; } catch (e) { if (e.code === 401) return; }
  var cv = await chargerConvocations();
  var notif = cv && cv.convocations.length ? h("button", {class: "enfant" + (cv.non_lues ? " notif" : ""), onclick: ouvrirConvocations},
    h("b", {}, "Convocations" + (cv.non_lues ? " · " + cv.non_lues + " nouvelle" + (cv.non_lues > 1 ? "s" : "") : "")),
    h("span", {}, cv.non_lues ? "L'école vous a envoyé une convocation : touchez pour la lire." : "Voir les convocations reçues de l'école.")) : null;
  var cartes = etat.enfants.map(function (e) {
    return h("button", {class: "enfant", onclick: function () { ouvrirEnfant(e); }},
      h("b", {}, e.prenom + " " + e.nom), h("span", {}, (e.classe || "Classe non définie") + (e.annee ? " · " + e.annee : "")),
      e.acces ? null : h("span", {class: "ko"}, " · accès à renouveler"));
  });
  montrer(
    h("div", {class: "carte"}, h("h2", {}, "Bonjour" + (etat.parent ? ", " + etat.parent.nom : "")), h("p", {class: "note"}, "Touchez un enfant pour voir sa situation.")),
    notif,
    h("div", {}, cartes.length ? cartes : h("p", {class: "note"}, "Aucun enfant lié à ce compte.")),
    h("button", {class: "p", onclick: ajouterEnfant}, "Ajouter un enfant"),
    h("button", {class: "s", onclick: changerMdp}, "Changer mon mot de passe"));
  etat.timer = setInterval(function () { if (etat.jeton && !document.hidden) listeEnfants(); }, RAFRAICHIR_S * 2000);
}

/* ---------------------------------------------------------------- convocations reçues (notifications de la Direction de discipline) */
async function chargerConvocations() {
  try { return await api("GET", "/convocations"); } catch (e) { return null; }
}

function lettreConvocation(l) {
  return h("div", {class: "lettre"}, h("p", {class: "ec"}, l.ecole), h("p", {class: "sv"}, l.service), h("h2", {}, l.titre),
    l.lignes.map(function (x) { return h("p", {}, h("b", {}, x[0] + " : "), x[1]); }),
    l.instructions ? h("p", {}, h("b", {}, "Instructions : "), l.instructions) : null,
    h("p", {}, l.texte), h("p", {class: "sg"}, l.signature));
}

async function ouvrirConvocations() {
  arreterTimer();
  var d = await chargerConvocations();
  var cartes = d ? d.convocations.map(function (v) {
    var badge = v.statut === "ANNULEE" ? h("span", {class: "badge an"}, "Annulée") : (v.lue ? h("span", {class: "badge lu"}, "Lue") : h("span", {class: "badge nv"}, "Nouvelle"));
    return h("button", {class: "enfant" + (v.statut === "ENVOYEE" && !v.lue ? " notif" : ""), onclick: function () { ouvrirConvocation(v); }},
      h("b", {}, "Convocation · " + v.enfant), h("span", {}, "Rendez-vous le " + v.date + " à " + v.heure + " · "), badge);
  }) : [];
  montrer(h("button", {class: "s", onclick: listeEnfants}, "← Mes enfants"),
    h("div", {class: "carte"}, h("h2", {}, "Convocations"), h("p", {class: "note"}, "Les convocations envoyées par l'école pour vos enfants.")),
    h("div", {}, cartes.length ? cartes : h("p", {class: "note"}, "Aucune convocation reçue.")));
}

async function ouvrirConvocation(v) {
  arreterTimer();
  montrer(h("button", {class: "s", onclick: ouvrirConvocations}, "← Convocations"),
    v.statut === "ANNULEE" ? h("div", {class: "err"}, "Cette convocation a été annulée par l'école" + (v.motif_annulation ? " : " + v.motif_annulation : "") + ". Ne vous présentez pas.") : null,
    lettreConvocation(v.lettre),
    h("p", {class: "note"}, "Reçue le " + (v.envoyee_le || "") + ". En cas d'empêchement, prévenez la Direction de discipline."));
  if (!v.lue) { try { await api("POST", "/convocations/" + v.id + "/lue"); v.lue = true; } catch (e) {} }
}

function ajouterEnfant() {
  var zone = h("div"), btn = h("button", {class: "p", type: "submit"}, "Ajouter");
  var form = h("form", {onsubmit: surEnvoi(btn, async function () {
    vider(zone);
    try { await api("POST", "/enfants", {code: val("e_code")}); listeEnfants(); } catch (e) { zone.appendChild(boite(e.message)); }
  })}, champ("e_code", "Code d'accès du nouveau reçu", "text", {placeholder: "XXXX-XXXX-XXXX", autocapitalize: "characters"}), zone, btn);
  montrer(h("div", {class: "carte"}, h("h2", {}, "Ajouter un enfant"),
    h("p", {class: "note"}, "Payez à la caisse le frais du logiciel pour cet enfant, puis saisissez le code imprimé sur son reçu."), form,
    h("button", {class: "s", onclick: listeEnfants}, "← Retour")));
}

function changerMdp() {
  var zone = h("div"), btn = h("button", {class: "p", type: "submit"}, "Changer");
  var form = h("form", {onsubmit: surEnvoi(btn, async function () {
    vider(zone);
    try { var d = await api("POST", "/mot-de-passe", {ancien: document.getElementById("m_a").value, nouveau: document.getElementById("m_n").value}); ouvertureSession(d); }
    catch (e) { zone.appendChild(boite(e.message)); }
  })}, champ("m_a", "Mot de passe actuel", "password", {autocomplete: "current-password"}), champ("m_n", "Nouveau mot de passe", "password", {autocomplete: "new-password"}), zone, btn);
  montrer(h("div", {class: "carte"}, h("h2", {}, "Changer le mot de passe"), form, h("button", {class: "s", onclick: listeEnfants}, "← Retour")));
}

/* ---------------------------------------------------------------- un enfant */
var ONGLETS = [["frais", "Frais"], ["presences", "Présences"], ["conduite", "Conduite"], ["resultats", "Résultats"]];
var RENDU = {frais: rendreFrais, presences: rendrePresences, conduite: rendreConduite, resultats: rendreResultats};

function ouvrirEnfant(enfant, onglet) {
  arreterTimer();
  onglet = onglet || "frais";
  var contenu = h("div"), maj = h("div", {class: "maj"});
  var barre = h("div", {class: "onglets"}, ONGLETS.map(function (o) {
    return h("button", {class: o[0] === onglet ? "on" : "", onclick: function () { ouvrirEnfant(enfant, o[0]); }}, o[1]);
  }));
  montrer(h("button", {class: "s", onclick: listeEnfants}, "← Mes enfants"),
    h("div", {class: "carte"}, h("h2", {}, enfant.prenom + " " + enfant.nom), h("span", {class: "note"}, (enfant.classe || "") + (enfant.annee ? " · " + enfant.annee : ""))),
    barre, contenu, maj);
  async function charger() {
    try {
      var d = await api("GET", "/enfants/" + enfant.id + "/" + onglet);
      vider(contenu); contenu.appendChild(RENDU[onglet](d));
      maj.textContent = "Mis à jour à " + new Date().toLocaleTimeString("fr-FR", {hour: "2-digit", minute: "2-digit", second: "2-digit"}) + " · actualisation automatique";
    } catch (e) {
      if (e.code === 401) return;
      vider(contenu); contenu.appendChild(boite(e.message));
      if (e.acces === false) arreterTimer();
    }
  }
  charger();
  etat.timer = setInterval(charger, RAFRAICHIR_S * 1000);
}

function carte() { var c = h("div", {class: "carte"}); for (var i = 0; i < arguments.length; i++) if (arguments[i]) c.appendChild(arguments[i]); return c; }
function enveloppe() { var d = h("div"); for (var i = 0; i < arguments.length; i++) if (arguments[i]) d.appendChild(arguments[i]); return d; }
function ligne(g, d, classe, sous) { return h("div", {class: "ligne"}, h("div", {}, g, sous ? h("div", {class: "d"}, sous) : null), h("div", {class: classe || ""}, d)); }
function classeStatut(s) { s = (s || "").toLowerCase(); return s.indexOf("sold") >= 0 || s.indexOf("pay") === 0 || s.indexOf("règle") >= 0 ? "ok" : (s.indexOf("part") >= 0 || s.indexOf("cours") >= 0 ? "att" : "ko"); }
function nonInscrit(d, texte) { return d.inscrit === false ? carte(h("p", {class: "note"}, texte || "Cet enfant n'est pas inscrit pour l'année en cours.")) : null; }

function rendreFrais(d) {
  var nI = nonInscrit(d); if (nI) return nI;
  var tot = d.totaux.map(function (t) {
    return h("div", {class: "stats"}, h("div", {class: "stat"}, "À payer", h("b", {}, t.du.texte)), h("div", {class: "stat"}, "Payé", h("b", {class: "ok"}, t.paye.texte)),
      h("div", {class: "stat"}, "Reste", h("b", {class: t.reste.centimes > 0 ? "ko" : "ok"}, t.reste.texte)));
  });
  var lignes = d.lignes.map(function (l) {
    return ligne(l.designation, l.reste.centimes > 0 ? "Reste " + l.reste.texte : "Soldé", l.reste.centimes > 0 ? "ko" : "ok",
      "Payé " + l.paye.texte + " sur " + l.du.texte + (l.prochain ? " · prochain versement " + l.prochain.texte : ""));
  });
  var dettes = d.dettes_anterieures.map(function (x) { return ligne("Année " + x.annee, x.reste.texte, "ko", "Dette antérieure"); });
  var recus = d.paiements.map(function (p) { return ligne(p.frais, p.montant.texte, "", "Reçu n° " + p.n_recu + " · " + p.date); });
  return enveloppe(carte(h("h2", {}, "Situation " + d.annee), enveloppe.apply(null, tot), lignes.length ? enveloppe.apply(null, lignes) : h("p", {class: "note"}, "Aucun frais défini.")),
    dettes.length ? carte(h("h2", {}, "Dettes des années précédentes"), enveloppe.apply(null, dettes)) : null,
    recus.length ? carte(h("h2", {}, "Paiements enregistrés"), enveloppe.apply(null, recus)) : null);
}

function dateFr(iso) { var p = String(iso).slice(0, 10).split("-"); return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : iso; }
function rendrePresences(d) {
  var jours = d.jours.map(function (j) {
    return ligne(dateFr(j.date), j.statut === "P" ? "Présent" : "Absent", j.statut === "P" ? "ok" : "ko", j.manques.length ? "Cours manqués : " + j.manques.join(", ") : null);
  });
  return enveloppe(carte(h("h2", {}, "Présences " + d.annee),
    h("div", {class: "stats"}, h("div", {class: "stat"}, "Présent", h("b", {class: "ok"}, d.presents)), h("div", {class: "stat"}, "Absent", h("b", {class: "ko"}, d.absents)),
      h("div", {class: "stat"}, "Taux", h("b", {}, d.taux === null ? "–" : d.taux + " %")))),
    carte(jours.length ? enveloppe.apply(null, jours) : h("p", {class: "note"}, "Aucune présence pointée pour le moment.")));
}

function rendreConduite(d) {
  var nI = nonInscrit(d); if (nI) return nI;
  var blocs = d.periodes.map(function (p) {
    return carte(ligne(p.periode, (p.cote || "–") + (p.libelle ? " · " + p.libelle : ""), "", p.semestre || null),
      p.par_cours.length ? enveloppe.apply(null, p.par_cours.map(function (c) { return ligne(c.cours, c.cote + " · " + c.libelle, "note"); })) : null);
  });
  var legende = d.legende.map(function (l) { return l.code + " = " + l.libelle; }).join(" · ");
  return enveloppe(carte(h("h2", {}, "Conduite " + d.annee), h("p", {class: "note"}, legende)), enveloppe.apply(null, blocs));
}

function rendreResultats(d) {
  var nI = nonInscrit(d); if (nI) return nI;
  if (!d.colonnes.length) return carte(h("p", {class: "note"}, "Aucun résultat disponible pour le moment."));
  var tete = h("tr", {}, h("th", {class: "l"}, "Cours"), d.colonnes.map(function (c) { return h("th", {}, c.libelle); }));
  var corps = d.cours.map(function (c) {
    return h("tr", {}, h("td", {class: "l"}, c.libelle, c.professeur ? h("div", {class: "d note"}, c.professeur) : null),
      d.colonnes.map(function (col) { var x = c.cotes[col.cle]; return h("td", {}, x ? x.obtenu + "/" + x.max : "–"); }));
  });
  var parCle = {}; d.totaux.forEach(function (t) { parCle[t.cle] = t; });
  function lig(nom, f) { return h("tr", {class: "tot"}, h("td", {class: "l"}, nom), d.colonnes.map(function (col) { var t = parCle[col.cle]; return h("td", {}, t ? f(t) : "–"); })); }
  var pied = [
    lig("Total", function (t) { return t.obtenu === null || t.obtenu === undefined ? "–" : t.obtenu + "/" + t.max; }),
    lig("Pourcentage", function (t) { return t.pct === null || t.pct === undefined ? "–" : t.pct + " %"; }),
    lig("Rang", function (t) { return t.rang ? t.rang + "/" + t.effectif : "–"; }),
    lig("Résultat", function (t) { return t.resultat || t.mention || "–"; })
  ];
  return carte(h("h2", {}, "Résultats " + d.annee + (d.classe ? " · " + d.classe : "")), h("p", {class: "note"}, "Seuil de réussite : " + d.seuil + " %"),
    h("div", {class: "defile"}, h("table", {}, h("thead", {}, tete), h("tbody", {}, corps, pied))));
}

/* ---------------------------------------------------------------- démarrage */
(async function () {
  if (etat.jeton) {
    try { etat.enfants = (await api("GET", "/enfants")).enfants; btnOut.hidden = false; listeEnfants(); return; } catch (e) { sauverJeton(null); }
  }
  accueil();
})();
</script></body></html>
"""
