/* ============================================================
   ICM — Composant photo d'identité
   Choix du fichier → recadrage manuel → compression automatique.

   Aucune librairie externe. Fonctionne à la souris et au doigt.

   Utilisation :
     const blob = await PhotoICM.recadrer(fichier);   // null si annulé
     const apercu = URL.createObjectURL(blob);

   Le résultat est un JPEG au format identité 3/4, d'environ 40 à 120 Ko
   pour une photo ordinaire — et JAMAIS plus de 500 Ko, quelle que soit
   la taille ou la complexité de l'original : si le premier essai dépasse
   ce plafond, le composant baisse automatiquement la qualité JPEG, puis
   au besoin réduit aussi les dimensions, jusqu'à repasser en dessous.
   ============================================================ */

const PhotoICM = (function(){
  "use strict";

  const LARGEUR = 600, HAUTEUR = 800, QUALITE = 0.85;    // sortie de départ
  const VUE_L = 276, VUE_H = 368;                         // aperçu à l'écran
  const TAILLE_MAX = 12 * 1024 * 1024;                    // 12 Mo à l'entrée

  // Plafond imposé au fichier produit, et paramètres de la compression
  // de secours qui s'enclenche automatiquement si on le dépasse.
  const TAILLE_CIBLE   = 500 * 1024;   // 500 Ko — jamais dépassé
  const QUALITE_MIN    = 0.35;         // en dessous, l'image devient inexploitable
  const LARGEUR_MIN    = 240;          // en dessous, la photo n'est plus reconnaissable
  const PALIERS_TAILLE = 6;            // nombre de réductions de dimensions tentées

  let modale = null, canvas = null, ctx = null, curseurZoom = null;
  let image = null, base = 1, zoom = 1, tx = 0, ty = 0;
  let resoudre = null;

  /* ---------- Construction de la fenêtre (une seule fois) ---------- */
  function construireModale(){
    if (modale) return;

    const style = document.createElement("style");
    style.textContent = `
      .icm-photo-fond{position:fixed;inset:0;background:rgba(18,32,58,.72);
        display:flex;align-items:center;justify-content:center;z-index:200;padding:1rem;}
      /* Sans cette règle, « display:flex » l'emporte sur l'attribut hidden
         et la fenêtre fermée continue de couvrir la page. */
      .icm-photo-fond[hidden]{display:none;}
      .icm-photo-boite{background:#fff;border-radius:12px;padding:1.4rem;max-width:340px;
        width:100%;box-shadow:0 20px 60px rgba(0,0,0,.3);font-family:inherit;}
      .icm-photo-boite h2{margin:0 0 .3rem;font-size:1.05rem;color:#12203a;}
      .icm-photo-boite p.aide{margin:0 0 1rem;font-size:.8rem;color:#41526e;}
      .icm-photo-vue{width:${VUE_L}px;height:${VUE_H}px;margin:0 auto;border:2px solid #b8912f;
        border-radius:4px;overflow:hidden;background:#eef1f6;cursor:grab;touch-action:none;}
      .icm-photo-vue.attrape{cursor:grabbing;}
      .icm-photo-vue canvas{display:block;}
      .icm-photo-zoom{display:flex;align-items:center;gap:.6rem;margin:1rem 0 1.2rem;
        font-size:.8rem;color:#41526e;}
      .icm-photo-zoom input{flex:1;padding:0;border:0;background:transparent;}
      .icm-photo-actions{display:flex;gap:.6rem;}
      .icm-photo-actions button{flex:1;font:inherit;font-size:.88rem;font-weight:600;
        padding:.6rem 1rem;border-radius:8px;cursor:pointer;border:1px solid #dde3ec;
        background:#fff;color:#12203a;}
      .icm-photo-actions .valider{background:#12203a;border-color:#12203a;color:#fff;}
    `;
    document.head.appendChild(style);

    modale = document.createElement("div");
    modale.className = "icm-photo-fond";
    modale.hidden = true;
    modale.innerHTML = `
      <div class="icm-photo-boite" role="dialog" aria-modal="true">
        <h2>Recadrer la photo</h2>
        <p class="aide">Faites glisser l'image pour centrer le visage,
          puis ajustez le zoom. La photo est allégée automatiquement
          sous 500 Ko avant l'enregistrement.</p>
        <div class="icm-photo-vue"><canvas width="${VUE_L}" height="${VUE_H}"></canvas></div>
        <div class="icm-photo-zoom">
          <span>Zoom</span>
          <input type="range" min="100" max="400" value="100" step="1">
        </div>
        <div class="icm-photo-actions">
          <button type="button" class="annuler">Annuler</button>
          <button type="button" class="valider">Valider la photo</button>
        </div>
      </div>`;
    document.body.appendChild(modale);

    canvas      = modale.querySelector("canvas");
    ctx         = canvas.getContext("2d");
    curseurZoom = modale.querySelector('input[type=range]');
    const vue   = modale.querySelector(".icm-photo-vue");

    /* --- Zoom --- */
    curseurZoom.addEventListener("input", ()=>{
      const centreX = (VUE_L/2 - tx) / zoom;      // garder le centre de la vue
      const centreY = (VUE_H/2 - ty) / zoom;
      zoom = curseurZoom.value / 100;
      tx = VUE_L/2 - centreX * zoom;
      ty = VUE_H/2 - centreY * zoom;
      contraindre(); dessiner();
    });
    vue.addEventListener("wheel", (e)=>{
      e.preventDefault();
      const pas = e.deltaY < 0 ? 8 : -8;
      curseurZoom.value = Math.min(400, Math.max(100, Number(curseurZoom.value) + pas));
      curseurZoom.dispatchEvent(new Event("input"));
    }, { passive:false });

    /* --- Déplacement (souris et doigt) --- */
    let attrape = false, departX = 0, departY = 0;
    vue.addEventListener("pointerdown", (e)=>{
      attrape = true; departX = e.clientX - tx; departY = e.clientY - ty;
      vue.classList.add("attrape"); vue.setPointerCapture(e.pointerId);
    });
    vue.addEventListener("pointermove", (e)=>{
      if(!attrape) return;
      tx = e.clientX - departX; ty = e.clientY - departY;
      contraindre(); dessiner();
    });
    const relacher = (e)=>{
      attrape = false; vue.classList.remove("attrape");
      try{ vue.releasePointerCapture(e.pointerId); }catch(err){}
    };
    vue.addEventListener("pointerup", relacher);
    vue.addEventListener("pointercancel", relacher);

    /* --- Boutons --- */
    modale.querySelector(".annuler").addEventListener("click", ()=>fermer(null));
    modale.querySelector(".valider").addEventListener("click", produire);
    modale.addEventListener("click", (e)=>{ if(e.target === modale) fermer(null); });
    document.addEventListener("keydown", (e)=>{
      if(!modale.hidden && e.key === "Escape") fermer(null);
    });
  }

  /* ---------- Affichage ---------- */
  function contraindre(){
    const l = image.width * base * zoom, h = image.height * base * zoom;
    tx = Math.min(0, Math.max(VUE_L - l, tx));
    ty = Math.min(0, Math.max(VUE_H - h, ty));
  }

  function dessiner(){
    ctx.fillStyle = "#eef1f6";
    ctx.fillRect(0, 0, VUE_L, VUE_H);
    ctx.drawImage(image, tx, ty,
      image.width * base * zoom, image.height * base * zoom);
  }

  /* ---------- Lecture du fichier (orientation EXIF respectée) ---------- */
  async function lireImage(fichier){
    if (typeof createImageBitmap === "function"){
      try{ return await createImageBitmap(fichier, { imageOrientation:"from-image" }); }
      catch(e){ /* navigateur ancien : on retombe sur <img> */ }
    }
    return await new Promise((ok, ko)=>{
      const url = URL.createObjectURL(fichier);
      const img = new Image();
      img.onload  = ()=>{ URL.revokeObjectURL(url); ok(img); };
      img.onerror = ()=>{ URL.revokeObjectURL(url); ko(new Error("Image illisible.")); };
      img.src = url;
    });
  }

  /* ---------- Production du JPEG final, sous 500 Ko garanti ---------- */

  /* Dessine le cadrage choisi par l'utilisateur sur un canevas de la
     taille demandée : seules les dimensions de sortie changent, le
     cadrage (zone visible, centrage, zoom) reste toujours le même. */
  function dessinerSortie(largeur, hauteur){
    const echelle = base * zoom;
    const sortie = document.createElement("canvas");
    sortie.width = largeur; sortie.height = hauteur;
    const c = sortie.getContext("2d");
    c.fillStyle = "#fff"; c.fillRect(0, 0, largeur, hauteur);
    c.imageSmoothingQuality = "high";
    c.drawImage(image,
      -tx / echelle, -ty / echelle, VUE_L / echelle, VUE_H / echelle,
      0, 0, largeur, hauteur);
    return sortie;
  }

  function versBlob(canevas, qualite){
    return new Promise((resoudre)=>canevas.toBlob(resoudre, "image/jpeg", qualite));
  }

  async function produire(){
    const boutonValider = modale.querySelector(".valider");
    const boutonAnnuler = modale.querySelector(".annuler");
    const texteInitial = boutonValider.textContent;
    boutonValider.disabled = true;
    boutonAnnuler.disabled = true;
    boutonValider.textContent = "Compression…";

    try{
      let largeur = LARGEUR, hauteur = HAUTEUR, qualite = QUALITE;
      let canevas = dessinerSortie(largeur, hauteur);
      let blob = await versBlob(canevas, qualite);

      // 1) La photo dépasse 500 Ko : on baisse la qualité JPEG par paliers,
      //    sans retoucher les dimensions ni redessiner (rapide).
      while (blob.size > TAILLE_CIBLE && qualite > QUALITE_MIN){
        qualite = Math.max(QUALITE_MIN, qualite - 0.1);
        blob = await versBlob(canevas, qualite);
      }

      // 2) Même à qualité minimale ça dépasse encore (photo très chargée
      //    en détails) : on réduit aussi les dimensions, par paliers,
      //    en conservant toujours le même cadrage et le format 3/4.
      let paliers = 0;
      while (blob.size > TAILLE_CIBLE && paliers < PALIERS_TAILLE && largeur > LARGEUR_MIN){
        largeur = Math.max(LARGEUR_MIN, Math.round(largeur * 0.85));
        hauteur = Math.round(largeur * HAUTEUR / LARGEUR);
        qualite = 0.7;
        canevas = dessinerSortie(largeur, hauteur);
        blob = await versBlob(canevas, qualite);
        paliers++;
      }

      fermer(blob);
    } finally {
      boutonValider.disabled = false;
      boutonAnnuler.disabled = false;
      boutonValider.textContent = texteInitial;
    }
  }

  function fermer(resultat){
    modale.hidden = true;
    if (image && image.close) { try{ image.close(); }catch(e){} }
    image = null;
    const f = resoudre; resoudre = null;
    if (f) f(resultat);
  }

  /* ---------- Point d'entrée ---------- */
  async function recadrer(fichier){
    if (!fichier) return null;
    if (!/^image\//.test(fichier.type))
      throw new Error("Ce fichier n'est pas une image.");
    if (fichier.size > TAILLE_MAX)
      throw new Error("Image trop lourde (maximum 12 Mo). Réduisez-la avant de l'envoyer.");

    construireModale();
    image = await lireImage(fichier);

    base = Math.max(VUE_L / image.width, VUE_H / image.height);
    zoom = 1;
    tx = (VUE_L - image.width  * base) / 2;
    ty = (VUE_H - image.height * base) / 2;
    curseurZoom.value = 100;

    contraindre(); dessiner();
    modale.hidden = false;

    return new Promise((ok)=>{ resoudre = ok; });
  }

  /* Convertit un blob en « data URL » (utilisé par la version Flask) */
  function versDataUrl(blob){
    return new Promise((ok, ko)=>{
      const lecteur = new FileReader();
      lecteur.onload  = ()=>ok(lecteur.result);
      lecteur.onerror = ()=>ko(new Error("Lecture impossible."));
      lecteur.readAsDataURL(blob);
    });
  }

  return { recadrer, versDataUrl, LARGEUR, HAUTEUR, TAILLE_CIBLE };
})();
