/**
 * UrbanReport - Controlador de Modal "Radicar Incidencia"
 * Mini-mapa interactivo con Leaflet, selección de categoría, evidencia fotográfica
 * y sincronización en tiempo real con el mapa global.
 */

(function () {
  'use strict';

  // ── Coordenadas predeterminadas (Medellín, Colombia) ──
  const MEDELLIN_LAT = 6.2442;
  const MEDELLIN_LNG = -75.5812;

  // ── Límites geográficos de Medellín (deben coincidir con el backend) ──
  const MEDELLIN_BOUNDS = {
    latMin: 6.19,
    latMax: 6.31,
    lngMin: -75.64,
    lngMax: -75.53,
  };

  function estaEnMedellin(lat, lng) {
    return (
      lat >= MEDELLIN_BOUNDS.latMin && lat <= MEDELLIN_BOUNDS.latMax &&
      lng >= MEDELLIN_BOUNDS.lngMin && lng <= MEDELLIN_BOUNDS.lngMax
    );
  }

  // ── Puntos de interés y barrios comunes de Medellín para búsqueda rápida ──
  const MEDELLIN_BARRIOS = {
    'el poblado': [6.208, -75.568],
    'poblado': [6.208, -75.568],
    'laureles': [6.245, -75.592],
    'centro': [6.251, -75.564],
    'la candelaria': [6.251, -75.564],
    'belen': [6.229, -75.598],
    'belén': [6.229, -75.598],
    'robledo': [6.275, -75.597],
    'estadio': [6.256, -75.590],
    'aranjuez': [6.278, -75.556],
    'castilla': [6.297, -75.574],
    'guayabal': [6.216, -75.586],
    'manrique': [6.269, -75.545],
    'buenos aires': [6.239, -75.552],
    'san javier': [6.252, -75.617],
    'comuna 13': [6.252, -75.617],
    'parque lleras': [6.2088, -75.5677],
    'parque de los deseos': [6.2708, -75.5644],
    'jardin botanico': [6.2711, -75.5623],
    'jardín botánico': [6.2711, -75.5623],
    'plaza botero': [6.2524, -75.5688],
  };

  // ── Elementos DOM ──
  const modalBackdrop = document.getElementById('radicarModal');
  const closeBtn = document.getElementById('btnCloseRadicar');
  const cancelBtn = document.getElementById('btnCancelRadicar');
  const radicarForm = document.getElementById('radicarIncidenciaForm');
  const categoryCards = document.querySelectorAll('.radicar-category-card');
  const categoriaInput = document.getElementById('radicarCategoria');
  const latInput = document.getElementById('radicarLat');
  const lngInput = document.getElementById('radicarLng');
  const ubicacionInput = document.getElementById('radicarUbicacion');
  const ubicacionFijadaInput = document.getElementById('radicarUbicacionFijada');

  // Tipos y tamaño permitidos para la evidencia fotográfica (validación en cliente)
  const TIPOS_IMAGEN_PERMITIDOS = ['image/png', 'image/jpeg'];
  const MAX_IMAGEN_BYTES = 8 * 1024 * 1024; // 8 MB

  // Marca que el usuario fijó una ubicación real (clic/arrastre/búsqueda/GPS)
  function marcarUbicacionFijada() {
    if (ubicacionFijadaInput) ubicacionFijadaInput.value = '1';
  }
  const coordsDisplay = document.getElementById('radicarCoordsDisplay');
  const submitBtn = document.getElementById('btnSubmitRadicar');
  const submitText = document.getElementById('btnSubmitText');

  // Dropzone elementos
  const dropzone = document.getElementById('radicarDropzone');
  const fileInput = document.getElementById('radicarImagenInput');
  const dropzonePrompt = document.getElementById('dropzonePrompt');
  const filePreview = document.getElementById('radicarFilePreview');
  const fileThumb = document.getElementById('radicarFileThumb');
  const fileName = document.getElementById('radicarFileName');
  const fileRemoveBtn = document.getElementById('radicarFileRemove');

  // Mini-mapa search input
  const miniMapSearch = document.getElementById('miniMapSearchInput');

  // ── Inicializar Canal de difusión en tiempo real ──
  let realtimeChannel = null;
  if ('BroadcastChannel' in window) {
    try {
      realtimeChannel = new BroadcastChannel('urbanreport_realtime_incidents');
    } catch (e) {
      console.warn('BroadcastChannel no soportado o deshabilitado:', e);
    }
  }

  // ── Leaflet Mini Map ──
  let miniMap = null;
  let miniMarker = null;

  function createMiniPinIcon() {
    return L.divIcon({
      className: 'radicar-map-pin-wrap',
      html: '<div class="radicar-map-pin"></div>',
      iconSize: [26, 26],
      iconAnchor: [13, 26],
    });
  }

  function initMiniMap() {
    if (miniMap || !document.getElementById('radicarMiniMap')) return;

    // Tile URL de ESRI Dark Gray
    const TILE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
    const TILE_ATTR = 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ';

    // Límites del mapa (Leaflet usa [[sur, oeste], [norte, este]])
    const leafletBounds = L.latLngBounds(
      [MEDELLIN_BOUNDS.latMin, MEDELLIN_BOUNDS.lngMin],
      [MEDELLIN_BOUNDS.latMax, MEDELLIN_BOUNDS.lngMax]
    );

    miniMap = L.map('radicarMiniMap', {
      center: [MEDELLIN_LAT, MEDELLIN_LNG],
      zoom: 14,
      minZoom: 12,
      maxZoom: 18,
      zoomControl: false,
      scrollWheelZoom: false, // Permite que la rueda del mouse haga scroll en el modal sin trabarse
      attributionControl: false,
      maxBounds: leafletBounds,
      maxBoundsViscosity: 1.0, // Impide arrastrar el mapa fuera de Medellín
    });

    // Control de zoom en la esquina inferior derecha
    L.control.zoom({ position: 'bottomright' }).addTo(miniMap);

    L.tileLayer(TILE_URL, {
      attribution: TILE_ATTR,
      // El basemap ESRI Dark Gray solo tiene tiles hasta ~zoom 16. Escalamos ese
      // último nivel disponible para zooms mayores en lugar de mostrar el
      // placeholder gris "Map data not yet available".
      maxZoom: 18,
      maxNativeZoom: 16,
    }).addTo(miniMap);

    // Marker con pin estilizado
    miniMarker = L.marker([MEDELLIN_LAT, MEDELLIN_LNG], {
      icon: createMiniPinIcon(),
      draggable: true,
    }).addTo(miniMap);

    // Evento arrastrar pin
    miniMarker.on('dragend', function (e) {
      const pos = e.target.getLatLng();
      if (!estaEnMedellin(pos.lat, pos.lng)) {
        // Revertir el pin a la última posición válida (o al centro de Medellín)
        showToast('El punto debe estar dentro de Medellín.');
        const prevLat = parseFloat(latInput && latInput.value) || MEDELLIN_LAT;
        const prevLng = parseFloat(lngInput && lngInput.value) || MEDELLIN_LNG;
        miniMarker.setLatLng([prevLat, prevLng]);
        return;
      }
      updateCoordinates(pos.lat, pos.lng);
    });

    // Evento clic en el mapa para posicionar el pin
    miniMap.on('click', function (e) {
      const lat = e.latlng.lat;
      const lng = e.latlng.lng;
      if (!estaEnMedellin(lat, lng)) {
        showToast('Solo puedes marcar ubicaciones dentro de Medellín.');
        return;
      }
      miniMarker.setLatLng([lat, lng]);
      updateCoordinates(lat, lng);
    });
  }

  function updateCoordinates(lat, lng) {
    const latFixed = Number(lat).toFixed(7);
    const lngFixed = Number(lng).toFixed(7);

    if (latInput) latInput.value = latFixed;
    if (lngInput) lngInput.value = lngFixed;
    if (coordsDisplay) {
      coordsDisplay.textContent = Number(lat).toFixed(4) + ', ' + Number(lng).toFixed(4);
    }
    if (ubicacionInput && !ubicacionInput.value.trim()) {
      ubicacionInput.value = 'Medellín (' + Number(lat).toFixed(4) + ', ' + Number(lng).toFixed(4) + ')';
    }
    // El usuario fijó un punto en el mapa → ubicación válida
    marcarUbicacionFijada();
  }

  // ── Búsqueda en el mini-mapa (Enter o botón "Ir" en móvil) ──
  const miniMapSearchBtn = document.getElementById('miniMapSearchBtn');

  function normalizarDireccionMedellin(raw) {
    let s = String(raw || '').trim();
    if (!s) return '';
    return s
      .replace(/\b(cll|cl)\.?\s*(?=\d)/gi, 'Calle ')
      .replace(/\b(cra|cr|kr|kra)\.?\s*(?=\d)/gi, 'Carrera ')
      .replace(/\b(dg|diag)\.?\s*(?=\d)/gi, 'Diagonal ')
      .replace(/\b(tv|trv|transv)\.?\s*(?=\d)/gi, 'Transversal ')
      .replace(/\b(cq|circ)\.?\s*(?=\d)/gi, 'Circular ')
      .replace(/\b(av|avda)\.?\s+/gi, 'Avenida ')
      .replace(/\b(no\.?|nro\.?|num\.?)\s*(?=\d)/gi, '# ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  async function ejecutarBusquedaMiniMapa() {
    if (!miniMapSearch) return;
    const rawQuery = miniMapSearch.value.trim();
    const query = rawQuery.toLowerCase();
    if (!query) return;

    // 1. Coincidencia exacta en lugares conocidos de Medellín
    if (Object.prototype.hasOwnProperty.call(MEDELLIN_BARRIOS, query)) {
      const coords = MEDELLIN_BARRIOS[query];
      if (setMiniMapLocation(coords[0], coords[1]) && ubicacionInput) {
        ubicacionInput.value = rawQuery;
      }
      return;
    }

    const normalized = normalizarDireccionMedellin(rawQuery);
    const hasCity = /medell[ií]n/i.test(normalized);
    const fullSingleLine = hasCity ? normalized : (normalized + ', Medellín, Antioquia, Colombia');
    const searchExtent = [
      MEDELLIN_BOUNDS.lngMin,
      MEDELLIN_BOUNDS.latMin,
      MEDELLIN_BOUNDS.lngMax,
      MEDELLIN_BOUNDS.latMax,
    ].join(',');

    // 2. Geocodificación precisa con ArcGIS World Geocoder acotado a Medellín
    try {
      const arcgisUrl =
        'https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates' +
        '?SingleLine=' + encodeURIComponent(fullSingleLine) +
        '&countryCode=COL' +
        '&searchExtent=' + encodeURIComponent(searchExtent) +
        '&location=' + encodeURIComponent(MEDELLIN_LNG + ',' + MEDELLIN_LAT) +
        '&outFields=Match_addr,Addr_type,StAddr,Nbrhd,PlaceName' +
        '&maxLocations=5&f=pjson';

      const res = await fetch(arcgisUrl);
      if (res.ok) {
        const data = await res.json();
        const candidates = (data && Array.isArray(data.candidates)) ? data.candidates : [];
        const genericTypes = new Set(['Locality', 'City', 'SubAdmin', 'Admin', 'AdministrativeArea', 'Postal']);

        for (const cand of candidates) {
          if (!cand || !cand.location) continue;
          const lat = parseFloat(cand.location.y);
          const lng = parseFloat(cand.location.x);
          if (!estaEnMedellin(lat, lng)) continue;

          const attrs = cand.attributes || {};
          const addrType = attrs.Addr_type || '';
          if (genericTypes.has(addrType) && !/^medell[ií]n$/i.test(rawQuery)) continue;
          if ((cand.score || 0) < 75) continue;

          const label =
            attrs.PlaceName ||
            attrs.StAddr ||
            (cand.address ? String(cand.address).split(',')[0].trim() : rawQuery);

          if (setMiniMapLocation(lat, lng) && ubicacionInput) {
            ubicacionInput.value = attrs.Nbrhd ? (label + ', ' + attrs.Nbrhd) : label;
          }
          return;
        }
      }
    } catch (err) {
      console.warn('ArcGIS mini-map fallback a Nominatim:', err);
    }

    // 3. Fallback: Geocodificación OSM Nominatim acotada al bounding box de Medellín
    const viewbox = [
      MEDELLIN_BOUNDS.lngMin, MEDELLIN_BOUNDS.latMax,
      MEDELLIN_BOUNDS.lngMax, MEDELLIN_BOUNDS.latMin
    ].join(',');
    const nominatimUrl = 'https://nominatim.openstreetmap.org/search?format=json&bounded=1&viewbox=' +
      encodeURIComponent(viewbox) + '&q=' +
      encodeURIComponent(fullSingleLine);

    fetch(nominatimUrl)
      .then(res => res.json())
      .then(data => {
        if (data && data.length > 0) {
          for (const item of data) {
            const lat = parseFloat(item.lat);
            const lng = parseFloat(item.lon);
            if (!estaEnMedellin(lat, lng)) continue;
            if (item.type === 'administrative' && !/^medell[ií]n$/i.test(rawQuery)) continue;
            if (setMiniMapLocation(lat, lng) && ubicacionInput) {
              ubicacionInput.value = item.display_name.split(',')[0];
            }
            return;
          }
        }
        showToast('No se encontró la dirección dentro de Medellín.');
      })
      .catch(() => {
        showToast('No se pudo buscar la dirección.');
      });
  }

  if (miniMapSearch) {
    miniMapSearch.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        ejecutarBusquedaMiniMapa();
      }
    });
  }
  if (miniMapSearchBtn) {
    miniMapSearchBtn.addEventListener('click', function (e) {
      e.preventDefault();
      ejecutarBusquedaMiniMapa();
    });
  }

  function setMiniMapLocation(lat, lng) {
    if (!miniMap || !miniMarker) return;
    if (!estaEnMedellin(lat, lng)) {
      showToast('Esa ubicación está fuera de Medellín. Elige un punto dentro de la ciudad.');
      return false;
    }
    miniMap.setView([lat, lng], 15);
    miniMarker.setLatLng([lat, lng]);
    updateCoordinates(lat, lng);
    return true;
  }

  // ── Selección de Categoría ──
  categoryCards.forEach(function (card) {
    card.addEventListener('click', function () {
      categoryCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      const cat = card.dataset.cat || 'VIAS';
      if (categoriaInput) categoriaInput.value = cat;
    });
  });

  // ── Dropzone de Evidencia Fotográfica ──
  if (dropzone && fileInput) {
    dropzone.addEventListener('click', function (e) {
      if (e.target.closest('#radicarFileRemove')) return;
      fileInput.click();
    });

    dropzone.addEventListener('dragover', function (e) {
      e.preventDefault();
      dropzone.style.borderColor = '#3b82f6';
      dropzone.style.background = '#182030';
    });

    dropzone.addEventListener('dragleave', function () {
      dropzone.style.borderColor = '';
      dropzone.style.background = '';
    });

    dropzone.addEventListener('drop', function (e) {
      e.preventDefault();
      dropzone.style.borderColor = '';
      dropzone.style.background = '';
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        fileInput.files = e.dataTransfer.files;
        handleSelectedFile(fileInput.files[0]);
      }
    });

    fileInput.addEventListener('change', function () {
      if (this.files && this.files[0]) {
        handleSelectedFile(this.files[0]);
      }
    });
  }

  function limpiarArchivoSeleccionado() {
    if (fileInput) fileInput.value = '';
    if (dropzonePrompt) dropzonePrompt.style.display = 'flex';
    if (filePreview) filePreview.style.display = 'none';
    if (fileThumb) fileThumb.src = '';
  }

  function handleSelectedFile(file) {
    if (!file) return;

    // Validación de tipo: solo PNG o JPG (por MIME y por extensión)
    const nombre = (file.name || '').toLowerCase();
    const extensionOk = /\.(png|jpe?g)$/.test(nombre);
    const tipoOk = TIPOS_IMAGEN_PERMITIDOS.indexOf(file.type) !== -1;
    if (!tipoOk || !extensionOk) {
      showToast('Formato no permitido. Solo se aceptan imágenes PNG o JPG.');
      limpiarArchivoSeleccionado();
      return;
    }

    // Validación de tamaño (máx. 8 MB)
    if (file.size > MAX_IMAGEN_BYTES) {
      showToast('La imagen supera el tamaño máximo permitido (8 MB).');
      limpiarArchivoSeleccionado();
      return;
    }

    if (fileName) fileName.textContent = file.name;
    if (dropzonePrompt) dropzonePrompt.style.display = 'none';
    if (filePreview) filePreview.style.display = 'flex';

    if (fileThumb) {
      const reader = new FileReader();
      reader.onload = function (e) {
        fileThumb.src = e.target.result;
      };
      reader.readAsDataURL(file);
    }
  }

  if (fileRemoveBtn) {
    fileRemoveBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (fileInput) fileInput.value = '';
      if (dropzonePrompt) dropzonePrompt.style.display = 'flex';
      if (filePreview) filePreview.style.display = 'none';
      if (fileThumb) fileThumb.src = '';
    });
  }

  // ── Botón Mi Ubicación en el Mini-Mapa ──
  const btnMiniLocate = document.getElementById('btnMiniLocate');
  if (btnMiniLocate) {
    btnMiniLocate.addEventListener('click', function () {
      if (!navigator.geolocation) {
        showToast('Geolocalización no disponible en este navegador.');
        return;
      }
      btnMiniLocate.style.opacity = '0.5';
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          btnMiniLocate.style.opacity = '1';
          // setMiniMapLocation ya avisa si el GPS cae fuera de Medellín
          if (setMiniMapLocation(pos.coords.latitude, pos.coords.longitude)) {
            showToast('Ubicación fijada con tu GPS actual.');
          }
        },
        function () {
          btnMiniLocate.style.opacity = '1';
          showToast('No se pudo obtener tu ubicación.');
        },
        { timeout: 8000 }
      );
    });
  }

  // ── Apertura y Cierre del Modal ──
  window.openRadicarModal = function () {
    if (!modalBackdrop) return;
    if (typeof window.closeMobileNav === 'function') {
      window.closeMobileNav();
    }
    modalBackdrop.classList.add('active');
    document.body.style.overflow = 'hidden';

    // Reiniciar posición de scroll al inicio
    const bodyEl = document.querySelector('.radicar-body');
    if (bodyEl) bodyEl.scrollTop = 0;

    // Si aún no hay coordenadas fijadas, inicializar en el punto predeterminado de Medellín
    if (latInput && lngInput && (!latInput.value.trim() || !lngInput.value.trim())) {
      updateCoordinates(MEDELLIN_LAT, MEDELLIN_LNG);
    }

    // Inicializar o refrescar Leaflet mini-map
    initMiniMap();
    setTimeout(function () {
      if (miniMap) {
        miniMap.invalidateSize();
        const curLat = parseFloat(latInput ? latInput.value : MEDELLIN_LAT) || MEDELLIN_LAT;
        const curLng = parseFloat(lngInput ? lngInput.value : MEDELLIN_LNG) || MEDELLIN_LNG;
        miniMap.setView([curLat, curLng], 14);
        if (miniMarker) miniMarker.setLatLng([curLat, curLng]);
      }
    }, 200);
  };

  window.openRadicarModalAt = function (lat, lng, ubicacionNombre) {
    const numLat = parseFloat(lat);
    const numLng = parseFloat(lng);
    if (!isNaN(numLat) && !isNaN(numLng) && estaEnMedellin(numLat, numLng)) {
      if (ubicacionInput && ubicacionNombre) {
        ubicacionInput.value = ubicacionNombre;
      }
      updateCoordinates(numLat, numLng);
    }
    window.openRadicarModal();
  };

  window.closeRadicarModal = function () {
    if (!modalBackdrop) return;
    modalBackdrop.classList.remove('active');
    document.body.style.overflow = '';
    resetSubmitBtn();
  };

  if (closeBtn) closeBtn.addEventListener('click', window.closeRadicarModal);
  if (cancelBtn) cancelBtn.addEventListener('click', window.closeRadicarModal);

  // Cerrar al hacer clic en el backdrop exterior
  if (modalBackdrop) {
    modalBackdrop.addEventListener('click', function (e) {
      if (e.target === modalBackdrop) {
        window.closeRadicarModal();
      }
    });
  }

  // Cerrar con Escape
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modalBackdrop && modalBackdrop.classList.contains('active')) {
      window.closeRadicarModal();
    }
  });

  // Interceptar botones existentes de la barra lateral y feed
  document.addEventListener('click', function (e) {
    const reportBtn = e.target.closest('.sidebar-report-btn, .composer-media-btn, .composer-input-btn, [data-open-radicar]');
    if (reportBtn) {
      e.preventDefault();
      window.openRadicarModal();
    }
  });

  function resetSubmitBtn() {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.style.opacity = '1';
    }
    if (submitText) {
      submitText.textContent = 'Confirmar y Enviar';
    }
  }

  // ── Toast Notification ──
  function showToast(message) {
    const toast = document.getElementById('urbanToast');
    const toastMsg = document.getElementById('urbanToastMsg');
    if (!toast) return;

    if (toastMsg) toastMsg.textContent = message;
    toast.classList.add('show');

    setTimeout(function () {
      toast.classList.remove('show');
    }, 4000);
  }

  // ── Envío del Formulario (Sincronización en Tiempo Real) ──
  if (radicarForm) {
    radicarForm.addEventListener('submit', function (e) {
      e.preventDefault();

      const titulo = document.getElementById('radicarTitulo')?.value.trim();
      const contenido = document.getElementById('radicarContenido')?.value.trim();

      if (!titulo && !contenido) {
        showToast('Por favor ingrese al menos un título o descripción.');
        return;
      }

      // Ubicación obligatoria: el usuario debe haber fijado un punto en el mapa
      const ubicacionFijada = ubicacionFijadaInput && ubicacionFijadaInput.value === '1';
      const tieneCoords = latInput && lngInput && latInput.value.trim() && lngInput.value.trim();
      if (!ubicacionFijada || !tieneCoords) {
        showToast('La ubicación es obligatoria. Marque el punto en el mapa o busque una dirección.');
        return;
      }

      // Estado de envío en botón
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.style.opacity = '0.75';
      }
      if (submitText) {
        submitText.textContent = 'Enviando...';
      }

      const formData = new FormData(radicarForm);

      fetch(radicarForm.action, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
        },
      })
        .then(function (res) {
          if (!res.ok) {
            throw new Error('Error en el servidor al guardar la incidencia.');
          }
          return res.json();
        })
        .then(function (data) {
          if (data.status === 'ok') {
            showToast('¡Incidencia radicada exitosamente!');
            window.closeRadicarModal();

            // Limpiar formulario
            radicarForm.reset();
            if (dropzonePrompt) dropzonePrompt.style.display = 'flex';
            if (filePreview) filePreview.style.display = 'none';
            if (fileThumb) fileThumb.src = '';
            if (categoriaInput) categoriaInput.value = 'VIAS';
            // Reiniciar estado de ubicación (obliga a fijarla de nuevo en el próximo reporte)
            if (ubicacionFijadaInput) ubicacionFijadaInput.value = '0';
            if (latInput) latInput.value = '';
            if (lngInput) lngInput.value = '';
            if (ubicacionInput) ubicacionInput.value = '';
            categoryCards.forEach(c => c.classList.remove('active'));
            if (categoryCards[0]) categoryCards[0].classList.add('active');

            // 1. Si estamos en la página del Mapa Global, reflejar inmediatamente
            if (typeof window.addIncidentToMap === 'function' && data.incidente) {
              window.addIncidentToMap(data.incidente, true);
            }

            // 2. Difundir en tiempo real a otras pestañas/ventanas
            if (realtimeChannel && data.incidente) {
              realtimeChannel.postMessage({
                type: 'NUEVA_INCIDENCIA',
                incidente: data.incidente,
              });
            }

            // 3. Fallback con localStorage para pestañas cruzadas
            if (data.incidente) {
              try {
                localStorage.setItem(
                  'urbanreport_realtime_event',
                  JSON.stringify({
                    timestamp: Date.now(),
                    incidente: data.incidente,
                  })
                );
              } catch (_) {}
            }

            // 4. Si estamos en el feed, reflejar en tiempo real con inserción dinámica
            if (typeof window.handleRealtimePostAdded === 'function' && data.incidente) {
              window.handleRealtimePostAdded(data.incidente);
            } else if (!document.getElementById('mapa') && window.location.pathname.includes('/feed/')) {
              setTimeout(function () {
                window.location.reload();
              }, 1200);
            }
          } else {
            showToast(data.message || 'Ocurrió un error al radicar.');
            resetSubmitBtn();
          }
        })
        .catch(function (err) {
          console.error('Error al radicar incidencia:', err);
          showToast('Error al procesar la solicitud.');
          resetSubmitBtn();
        });
    });
  }

})();
