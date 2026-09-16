/*
 * Suggerimenti per i campi indirizzo, come la casella di ricerca delle mappe.
 *
 * Si attacca da solo a ogni <input data-suggerimenti>. Mentre si scrive
 * interroga un servizio di indirizzi e propone via, civico, CAP e citta';
 * scegliendo una voce il campo viene riempito per intero.
 *
 * Due servizi, entrambi gratuiti e senza chiave:
 *   - Photon (komoot), fatto apposta per i suggerimenti mentre si scrive;
 *   - Nominatim (OpenStreetMap) di riserva, se il primo non risponde.
 * Se non risponde nessuno il campo resta un normale campo di testo: si
 * scrive l'indirizzo a mano e si va avanti lo stesso.
 */
(function () {
  "use strict";

  var ATTESA = 350;        // millisecondi di pausa prima di interrogare
  var MIN_CARATTERI = 5;
  var MAX_VOCI = 5;

  var servizio = "photon";   // passa a "nominatim" se photon non risponde

  function componi(via, civico, cap, citta) {
    var riga = via || "";
    if (riga && civico) riga += " " + civico;
    var coda = [cap, citta].filter(Boolean).join(" ");
    return [riga, coda].filter(Boolean).join(", ");
  }

  function daPhoton(dati) {
    return (dati.features || []).map(function (f) {
      var p = f.properties || {};
      return componi(p.street || p.name, p.housenumber, p.postcode,
                     p.city || p.county || p.state);
    });
  }

  function daNominatim(dati) {
    return (dati || []).map(function (r) {
      var a = r.address || {};
      return componi(a.road || a.pedestrian || r.name, a.house_number,
                     a.postcode, a.city || a.town || a.village || a.municipality);
    });
  }

  function cerca(testo, segnale) {
    var q = encodeURIComponent(testo);
    if (servizio === "photon") {
      return fetch("https://photon.komoot.io/api?q=" + q +
                   "&lang=it&limit=" + MAX_VOCI, { signal: segnale })
        .then(function (r) { return r.json(); })
        .then(daPhoton)
        .catch(function (e) {
          if (e.name === "AbortError") throw e;
          // Photon non raggiungibile: da qui in poi si usa l'altro
          servizio = "nominatim";
          return cerca(testo, segnale);
        });
    }
    return fetch("https://nominatim.openstreetmap.org/search?format=jsonv2" +
                 "&addressdetails=1&countrycodes=it&limit=" + MAX_VOCI +
                 "&q=" + q,
                 { signal: segnale, headers: { "Accept-Language": "it" } })
      .then(function (r) { return r.json(); })
      .then(daNominatim);
  }

  function attacca(campo) {
    var tendina = document.createElement("div");
    tendina.className = "suggerimenti";
    tendina.hidden = true;
    campo.parentNode.insertBefore(tendina, campo.nextSibling);
    if (getComputedStyle(campo.parentNode).position === "static") {
      campo.parentNode.style.position = "relative";
    }
    campo.setAttribute("autocomplete", "off");

    var timer = null, controllo = null, evidenziata = -1, voci = [];

    function chiudi() {
      tendina.hidden = true;
      evidenziata = -1;
    }

    function disegna() {
      if (!voci.length) { chiudi(); return; }
      tendina.innerHTML = "";
      voci.forEach(function (testo, i) {
        var riga = document.createElement("div");
        riga.className = "suggerimento" + (i === evidenziata ? " attivo" : "");
        riga.textContent = testo;
        // mousedown e non click: il click arriverebbe dopo il blur del campo,
        // quando la tendina e' gia' stata chiusa
        riga.addEventListener("mousedown", function (e) {
          e.preventDefault();
          scegli(i);
        });
        tendina.appendChild(riga);
      });
      tendina.hidden = false;
    }

    function scegli(i) {
      if (i < 0 || i >= voci.length) return;
      campo.value = voci[i];
      chiudi();
    }

    campo.addEventListener("input", function () {
      var testo = campo.value.trim();
      clearTimeout(timer);
      if (controllo) controllo.abort();
      if (testo.length < MIN_CARATTERI) { chiudi(); return; }
      timer = setTimeout(function () {
        controllo = new AbortController();
        cerca(testo, controllo.signal)
          .then(function (risultati) {
            voci = risultati.filter(function (t, i, a) {
              return t && t.length > 3 && a.indexOf(t) === i;
            }).slice(0, MAX_VOCI);
            evidenziata = -1;
            disegna();
          })
          .catch(function () { chiudi(); });   // in silenzio: resta testo libero
      }, ATTESA);
    });

    campo.addEventListener("keydown", function (e) {
      if (tendina.hidden) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        evidenziata = Math.min(evidenziata + 1, voci.length - 1);
        disegna();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        evidenziata = Math.max(evidenziata - 1, 0);
        disegna();
      } else if (e.key === "Enter") {
        if (evidenziata >= 0) { e.preventDefault(); scegli(evidenziata); }
      } else if (e.key === "Escape") {
        chiudi();
      }
    });

    campo.addEventListener("blur", function () { setTimeout(chiudi, 150); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("input[data-suggerimenti]").forEach(attacca);
  });
})();
