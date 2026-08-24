/* ============================================================
   ICM — Composant photo d'identité
   Choix du fichier → recadrage manuel → compression automatique.

   Aucune librairie externe. Fonctionne à la souris et au doigt.

   Utilisation :
     const blob = await PhotoICM.recadrer(fichier);   // null si annulé
     const apercu = URL.createObjectURL(blob);

   Le résultat est toujours un JPEG 600 × 800 (format identité 3/4),
   d'environ 40 à 90 Ko, quelle que soit la taille de l'original.
   ============================================================ */

const PhotoICM = (function(){
  "use strict";

  const LARGEUR = 600, HAUTEUR = 800, QUALITE = 0.85;   // sortie
  const VUE_L = 276, VUE_H = 368;                        // aperçu à l'écran
  const TAILLE_MAX = 12 * 1024 * 1024;                   // 12 Mo à l'entrée

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
          puis ajustez le zoom.</p>
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

  /* ---------- Production du JPEG final ---------- */
  function produire(){
    const echelle = base * zoom;
    const sortie = document.createElement("canvas");
    sortie.width = LARGEUR; sortie.height = HAUTEUR;
    const c = sortie.getContext("2d");
    c.fillStyle = "#fff"; c.fillRect(0, 0, LARGEUR, HAUTEUR);
    c.imageSmoothingQuality = "high";
    c.drawImage(image,
      -tx / echelle, -ty / echelle, VUE_L / echelle, VUE_H / echelle,
      0, 0, LARGEUR, HAUTEUR);
    sortie.toBlob((blob)=>fermer(blob), "image/jpeg", QUALITE);
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

  return { recadrer, versDataUrl, LARGEUR, HAUTEUR };
})();
