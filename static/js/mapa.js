/**
 * UrbanReport – Mapa Interactivo de Incidentes
 * Leaflet + OpenStreetMap con tema oscuro centrado en Medellín.
 * Sincronización en tiempo real y buscador instantáneo de direcciones y lugares.
 */

(function () {
  'use strict';

  // ── Coordenadas centrales de Medellín ──
  const MEDELLIN_LAT = 6.2442;
  const MEDELLIN_LNG = -75.5812;
  const DEFAULT_ZOOM = 13;

  // ── Mosaicos ESRI World Dark Gray Canvas ──
  const TILE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
  const TILE_ATTR = 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ';

  // ── Mapeos de Estado y Categoría ──
  const STATUS_COLORS = {
    REPORTADO: '#94a3b8',
    EN_PROCESO: '#f59e0b',
    RESUELTA: '#22c55e',
  };

  const CATEGORY_NAMES = {
    VIAS: 'Vías',
    ALUMBRADO: 'Alumbrado',
    PARQUES: 'Parques',
    INFRAESTRUCTURA: 'Infraestructura',
    REDES: 'Redes y Telecom.',
    ASEO: 'Aseo y Basuras',
    OTROS: 'Otros',
  };

  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // ── Base de datos de barrios, comunas, avenidas y lugares clave de Medellín ──
  const MEDELLIN_BARRIOS = {
    'el poblado': [6.208, -75.568],
    'poblado': [6.208, -75.568],
    'laureles': [6.245, -75.592],
    'centro': [6.251, -75.564],
    'la candelaria': [6.251, -75.564],
    'bello': [6.333, -75.558],
    'envigado': [6.170, -75.583],
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
    'itagui': [6.174, -75.612],
    'itagüí': [6.174, -75.612],
    'sabaneta': [6.151, -75.615],
    'parque lleras': [6.2088, -75.5677],
    'parque de los deseos': [6.2708, -75.5644],
    'jardin botanico': [6.2711, -75.5623],
    'jardín botánico': [6.2711, -75.5623],
    'parque explora': [6.2715, -75.5658],
    'plaza botero': [6.2524, -75.5688],
    'parque berrio': [6.2498, -75.5683],
    'parque berrío': [6.2498, -75.5683],
    'calle 10': [6.2090, -75.5700],
    'calle 33': [6.2360, -75.5800],
    'calle 44': [6.2478, -75.5752],
    'calle 50': [6.2530, -75.5780],
    'san juan': [6.2478, -75.5752],
    'las vegas': [6.2023, -75.5768],
    'carrera 43a': [6.2100, -75.5720],
    'avenida oriental': [6.2505, -75.5645],
    'carrera 80': [6.2480, -75.6020],
    'carrera 70': [6.2470, -75.5890],
    'circular 73': [6.2460, -75.5930],
    'metro poblado': [6.2120, -75.5775],
    'metro estadio': [6.2532, -75.5880],
    'metro san antonio': [6.2474, -75.5694],
    'metro acevedo': [6.3006, -75.5583],
  };

  const MEDELLIN_PLACES_LIST = Object.entries(MEDELLIN_BARRIOS).map(([key, coords]) => ({
    name: key.charAt(0).toUpperCase() + key.slice(1),
    sub: 'Medellín, Colombia',
    coords: coords,
  }));

  // ── Inicializar Mapa ──
  const map = L.map('mapa', {
    center: [MEDELLIN_LAT, MEDELLIN_LNG],
    zoom: DEFAULT_ZOOM,
    maxZoom: 18,
    zoomControl: false,
    attributionControl: true,
  });

  L.tileLayer(TILE_URL, {
    attribution: TILE_ATTR,
    // El basemap ESRI Dark Gray solo tiene tiles hasta ~zoom 16. Escalamos ese
    // último nivel disponible para zooms mayores en lugar de mostrar el
    // placeholder gris "Map data not yet available".
    maxZoom: 18,
    maxNativeZoom: 16,
  }).addTo(map);

  // ── Capas de marcadores ──
  let markersLayer = L.layerGroup().addTo(map);
  let searchTargetLayer = L.layerGroup().addTo(map);
  const existingMarkersMap = new Map(); // id -> marker

  // ── Icono para incidencias ──
  function createMarkerIcon(estado) {
    const cssClass = 'marker-' + (estado || 'reportado').toLowerCase();
    return L.divIcon({
      className: 'marker-icon-wrapper',
      html: '<div class="marker-pin ' + cssClass + '"></div>',
      iconSize: [28, 36],
      iconAnchor: [14, 36],
      popupAnchor: [0, -38],
    });
  }

  // ── Icono para búsquedas ──
  function createSearchPinIcon() {
    return L.divIcon({
      className: 'search-target-pin-wrap',
      html: '<div class="search-target-pin"></div>',
      iconSize: [30, 30],
      iconAnchor: [15, 30],
      popupAnchor: [0, -32],
    });
  }

  // ── Build popup HTML para incidencias ──
  function buildPopupHTML(inc) {
    const estado = inc.estado || 'REPORTADO';
    const statusClass = 'status-' + escapeHtml(estado.toLowerCase());
    const catName = escapeHtml(CATEGORY_NAMES[inc.categoria] || inc.categoria_display || inc.categoria || 'Incidente');
    const rawContent = String(inc.contenido || '');
    const snippet = escapeHtml(rawContent.substring(0, 140) + (rawContent.length > 140 ? '...' : ''));
    const detailUrl = inc.id ? '/feed/publicacion/' + inc.id + '/' : '';
    const isCensored = Boolean(inc.censurado);

    let imgHtml = '';
    if (inc.imagen_url) {
      if (isCensored) {
        // En el mapa: la imagen censurada tiene filtro reforzado, escudo y NO permite interacción
        imgHtml = '<div class="popup-media-container popup-media-censored" title="Imagen censurada por moderación">' +
            '<img src="' + escapeHtml(inc.imagen_url) + '" alt="Contenido censurado" loading="lazy" decoding="async" class="popup-media-img popup-img-censored">' +
            '<div class="popup-censor-overlay">' +
              '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>' +
                '<line x1="12" y1="9" x2="12" y2="13"/>' +
                '<line x1="12" y1="17" x2="12.01" y2="17"/>' +
              '</svg>' +
              '<span>Imagen censurada</span>' +
            '</div>' +
          '</div>';
      } else {
        imgHtml = '<div class="popup-media-container">' +
          (detailUrl
            ? '<a href="' + detailUrl + '" class="popup-media-link" title="Ver detalles y comentarios">' +
                '<img src="' + escapeHtml(inc.imagen_url) + '" alt="Evidencia" loading="lazy" decoding="async" class="popup-media-img">' +
              '</a>'
            : '<img src="' + escapeHtml(inc.imagen_url) + '" alt="Evidencia" loading="lazy" decoding="async" class="popup-media-img">') +
        '</div>';
      }
    }

    const censoredBadge = isCensored
      ? '<div class="popup-censored-badge">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>' +
          '<span>Publicación censurada</span>' +
        '</div>'
      : '';

    const titleHtml = inc.titulo
      ? '<div style="font-weight: 700; color: #ffffff; font-size: 0.95rem; margin-bottom: 4px;">' +
          (detailUrl
            ? '<a href="' + detailUrl + '" class="popup-title-link" title="Ver detalles y comentarios">' + escapeHtml(inc.titulo) + '</a>'
            : escapeHtml(inc.titulo)) +
        '</div>'
      : '';

    const contentParagraph = isCensored
      ? '<p class="popup-content-text popup-text-censored">' + snippet + '</p>'
      : '<p class="popup-content-text">' + snippet + '</p>';

    return (
      '<div class="popup-card">' +
        censoredBadge +
        '<div style="display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px;">' +
          '<span class="popup-status ' + statusClass + '">' + escapeHtml(inc.estado_display || estado) + '</span>' +
          '<span style="font-size: 0.72rem; padding: 2px 6px; background: #1e293b; color: #93c5fd; border-radius: 4px; font-weight: 600;">' + catName + '</span>' +
        '</div>' +
        titleHtml +
        (inc.ubicacion
          ? '<div class="popup-location">' +
              '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>' +
              escapeHtml(inc.ubicacion) +
            '</div>'
          : '') +
        imgHtml +
        contentParagraph +
        '<div class="popup-meta">' +
          '<span class="popup-author">' + escapeHtml(inc.autor) + '</span>' +
          '<span>' + escapeHtml(inc.tiempo || 'Hace un momento') + '</span>' +
          '<span>❤ ' + (Number(inc.likes) || 0) + '</span>' +
          '<span>💬 ' + (Number(inc.comentarios) || 0) + '</span>' +
          (detailUrl ? '<a href="' + detailUrl + '" class="popup-detail-link" title="Ver publicación y comentarios">Detalles →</a>' : '') +
        '</div>' +
      '</div>'
    );
  }


  // ── Agregar o actualizar marcador en tiempo real ──
  window.addIncidentToMap = function (inc, focus) {
    if (!inc || !inc.latitud || !inc.longitud) return;

    const lat = parseFloat(inc.latitud);
    const lng = parseFloat(inc.longitud);

    if (existingMarkersMap.has(inc.id)) {
      const existing = existingMarkersMap.get(inc.id);
      existing.setLatLng([lat, lng]);
      existing.setIcon(createMarkerIcon(inc.estado));
      existing.setPopupContent(buildPopupHTML(inc));
      existing._incData = inc;

      if (focus) {
        map.flyTo([lat, lng], 16, { duration: 1 });
        setTimeout(() => existing.openPopup(), 1050);
      }
      return;
    }

    const marker = L.marker([lat, lng], {
      icon: createMarkerIcon(inc.estado),
    });

    marker.bindPopup(buildPopupHTML(inc), {
      maxWidth: 290,
      minWidth: 230,
      closeButton: true,
    });

    marker._incData = inc;
    markersLayer.addLayer(marker);
    existingMarkersMap.set(inc.id, marker);

    if (focus) {
      const pulseCircle = L.circleMarker([lat, lng], {
        radius: 20,
        color: '#3b82f6',
        fillColor: '#60a5fa',
        fillOpacity: 0.5,
        weight: 3,
      }).addTo(map);

      setTimeout(() => {
        map.removeLayer(pulseCircle);
      }, 3500);

      map.flyTo([lat, lng], 16, { duration: 1.2 });
      setTimeout(() => {
        marker.openPopup();
      }, 1250);
    }
  };

  // ── Fetch incidents from API ──
  function loadIncidents(estado) {
    const param = estado && estado !== 'TODOS' ? '?estado=' + estado : '';
    const url = '/feed/api/incidentes-mapa/' + param;

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (!data || !data.incidentes) return;

        data.incidentes.forEach(function (inc) {
          if (existingMarkersMap.has(inc.id)) {
            const m = existingMarkersMap.get(inc.id);
            m.setPopupContent(buildPopupHTML(inc));
            m._incData = inc;
          } else {
            const marker = L.marker([inc.latitud, inc.longitud], {
              icon: createMarkerIcon(inc.estado),
            });
            marker.bindPopup(buildPopupHTML(inc), {
              maxWidth: 290,
              minWidth: 230,
              closeButton: true,
            });
            marker._incData = inc;
            markersLayer.addLayer(marker);
            existingMarkersMap.set(inc.id, marker);
          }
        });
      })
      .catch(function (err) {
        console.error('Error al cargar incidentes:', err);
      });
  }

  // ── Sincronización en tiempo real vía BroadcastChannel ──
  if ('BroadcastChannel' in window) {
    try {
      const channel = new BroadcastChannel('urbanreport_realtime_incidents');
      channel.onmessage = function (event) {
        if (event.data && event.data.type === 'NUEVA_INCIDENCIA' && event.data.incidente) {
          window.addIncidentToMap(event.data.incidente, true);
        }
      };
    } catch (e) {
      console.warn('BroadcastChannel no activo:', e);
    }
  }

  // ── Sincronización en tiempo real vía localStorage fallback ──
  window.addEventListener('storage', function (e) {
    if (e.key === 'urbanreport_realtime_event' && e.newValue) {
      try {
        const payload = JSON.parse(e.newValue);
        if (payload && payload.incidente) {
          window.addIncidentToMap(payload.incidente, true);
        }
      } catch (_) {}
    }
  });

  // ── Polling en segundo plano cada 12 segundos (solo si la pestaña está visible) ──
  setInterval(function () {
    if (!document.hidden) {
      loadIncidents(activeEstado);
    }
  }, 12000);

  // ── Botones de Filtro (Todos, Pendientes, En Revisión, Resueltas) ──
  const filterBtns = document.querySelectorAll('.mapa-filter-btn');
  let activeEstado = 'TODOS';

  filterBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      filterBtns.forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      activeEstado = btn.dataset.estado;

      markersLayer.eachLayer(function (marker) {
        if (!marker._incData) return;
        const inc = marker._incData;
        if (activeEstado === 'TODOS' || inc.estado === activeEstado) {
          if (!map.hasLayer(marker)) markersLayer.addLayer(marker);
          marker.setOpacity(1);
        } else {
          marker.setOpacity(0.08);
        }
      });
    });
  });

  // ══════════════════════════════════════════════════════════════════════════
  // ── MOTOR DE BÚSQUEDA DE DIRECCIONES Y LUGARES EN MEDELLÍN ──
  // ══════════════════════════════════════════════════════════════════════════
  const searchInput = document.getElementById('mapaSearchInput');
  const searchBtn = document.getElementById('mapaSearchBtn');
  const searchClear = document.getElementById('mapaSearchClear');
  const searchDropdown = document.getElementById('mapaSearchDropdown');
  let searchDebounceTimer = null;

  // Función para volar a la dirección y fijar un marcador
  function goToAddressLocation(name, sub, lat, lng, isIncident, incidentData) {
    searchTargetLayer.clearLayers();
    if (searchDropdown) searchDropdown.style.display = 'none';

    if (isIncident && incidentData) {
      if (existingMarkersMap.has(incidentData.id)) {
        const marker = existingMarkersMap.get(incidentData.id);
        map.flyTo([lat, lng], 16, { duration: 1.2 });
        setTimeout(() => marker.openPopup(), 1250);
        return;
      }
    }

    const targetMarker = L.marker([lat, lng], {
      icon: createSearchPinIcon(),
    });

    const safeName = escapeHtml(name);
    const safeSub = escapeHtml(sub);
    const jsSafeName = escapeHtml(String(name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
    const popupHtml = (
      '<div style="font-family: inherit; padding: 4px;">' +
        '<div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">' +
          '<span style="font-size:0.72rem; padding:2px 7px; background:#1e293b; color:#38bdf8; border-radius:4px; font-weight:700;">DIRECCIÓN ENCONTRADA</span>' +
        '</div>' +
        '<div style="font-weight:700; color:#ffffff; font-size:0.95rem; margin-bottom:4px;">' + safeName + '</div>' +
        (sub ? '<div style="color:#94a3b8; font-size:0.8rem; margin-bottom:10px;">' + safeSub + '</div>' : '') +
        '<button type="button" class="btn-primary" style="width:100%; font-size:0.8rem; padding:8px 12px; border-radius:6px; cursor:pointer;" ' +
          'onclick="if(window.openRadicarModal){window.openRadicarModal(); if(document.getElementById(\'radicarLat\')) document.getElementById(\'radicarLat\').value=\'' + Number(lat).toFixed(7) + '\'; if(document.getElementById(\'radicarLng\')) document.getElementById(\'radicarLng\').value=\'' + Number(lng).toFixed(7) + '\'; if(document.getElementById(\'radicarUbicacion\')) document.getElementById(\'radicarUbicacion\').value=\'' + jsSafeName + '\';}">' +
          '+ Reportar Incidente Aquí' +
        '</button>' +
      '</div>'
    );

    targetMarker.bindPopup(popupHtml, {
      maxWidth: 280,
      closeButton: true,
    });

    searchTargetLayer.addLayer(targetMarker);

    // Vuelo hacia la ubicación exacta
    map.flyTo([lat, lng], 16, { duration: 1.2 });
    setTimeout(() => {
      targetMarker.openPopup();
    }, 1250);
  }

  // ── Ejecutar búsqueda inmediata (Exacta como en el modal de radicar) ──
  function triggerSearch(rawQuery) {
    const query = (rawQuery || '').toLowerCase().trim();
    if (!query) return;

    if (searchDropdown) searchDropdown.style.display = 'none';

    // 1. Coincidencia directa en base de datos de Medellín
    if (MEDELLIN_BARRIOS[query]) {
      const coords = MEDELLIN_BARRIOS[query];
      goToAddressLocation(rawQuery.toUpperCase(), 'Medellín, Colombia', coords[0], coords[1], false);
      return;
    }

    // 2. Coincidencia parcial en base de datos de Medellín
    for (const [key, coords] of Object.entries(MEDELLIN_BARRIOS)) {
      if (query.includes(key) || key.includes(query)) {
        const title = key.charAt(0).toUpperCase() + key.slice(1);
        goToAddressLocation(title, 'Medellín, Colombia', coords[0], coords[1], false);
        return;
      }
    }

    // 3. Buscar si coincide con un incidente registrado en el mapa
    let matchedIncident = null;
    markersLayer.eachLayer(function (marker) {
      if (matchedIncident || !marker._incData) return;
      const inc = marker._incData;
      const fullText = ((inc.titulo || '') + ' ' + inc.contenido + ' ' + (inc.ubicacion || '') + ' #' + inc.id).toLowerCase();
      if (fullText.includes(query)) {
        matchedIncident = inc;
      }
    });

    if (matchedIncident) {
      goToAddressLocation(
        matchedIncident.titulo || matchedIncident.ubicacion || ('Incidente #' + matchedIncident.id),
        matchedIncident.ubicacion,
        matchedIncident.latitud,
        matchedIncident.longitud,
        true,
        matchedIncident
      );
      return;
    }

    // 4. Geocodificación OSM Nominatim para Medellín (igual que en modal_radicar.js)
    const nominatimUrl = 'https://nominatim.openstreetmap.org/search?format=json&q=' + 
      encodeURIComponent(query + ', Medellin, Colombia');

    fetch(nominatimUrl)
      .then(res => res.json())
      .then(data => {
        if (data && data.length > 0) {
          const item = data[0];
          const parts = item.display_name.split(',');
          const mainTitle = parts[0] + (parts[1] ? ', ' + parts[1].trim() : '');
          const subTitle = parts.slice(2, 4).join(', ').trim() || 'Medellín, Colombia';
          goToAddressLocation(mainTitle, subTitle, parseFloat(item.lat), parseFloat(item.lon), false);
        } else {
          alert('No se encontró la dirección "' + rawQuery + '" en Medellín.');
        }
      })
      .catch(err => {
        console.error('Error al buscar dirección:', err);
      });
  }

  // ── Sugerencias en tiempo real mientras escribe ──
  function performLiveSuggestions(query) {
    if (!query) {
      if (searchDropdown) searchDropdown.style.display = 'none';
      if (searchClear) searchClear.style.display = 'none';
      return;
    }

    if (searchClear) searchClear.style.display = 'flex';

    const normalizedQuery = query.toLowerCase().trim();
    const results = [];

    // Lugares locales
    MEDELLIN_PLACES_LIST.forEach(place => {
      const matchName = place.name.toLowerCase();
      if (matchName.includes(normalizedQuery)) {
        results.push({
          name: place.name,
          sub: place.sub,
          lat: place.coords[0],
          lng: place.coords[1],
          badge: 'Lugar',
          isIncident: false,
        });
      }
    });

    // Incidencias locales
    markersLayer.eachLayer(function (marker) {
      if (!marker._incData) return;
      const inc = marker._incData;
      const searchable = (
        (inc.titulo || '') + ' ' + 
        inc.contenido + ' ' + 
        (inc.ubicacion || '') + ' ' + 
        '#' + inc.id
      ).toLowerCase();

      if (searchable.includes(normalizedQuery)) {
        results.push({
          name: inc.titulo || inc.ubicacion || ('Incidente #' + inc.id),
          sub: inc.ubicacion || inc.contenido.substring(0, 45) + '...',
          lat: inc.latitud,
          lng: inc.longitud,
          badge: inc.estado_display || 'Incidencia',
          isIncident: true,
          incidentData: inc,
        });
      }
    });

    renderSearchResults(results, normalizedQuery);
  }

  // Renderizar dropdown
  function renderSearchResults(results, query) {
    if (!searchDropdown) return;

    if (!results || results.length === 0) {
      searchDropdown.innerHTML = (
        '<div style="padding: 12px; font-size: 0.82rem; color: #94a3b8; text-align: center;">' +
          'Presiona Enter para buscar "' + escapeHtml(query) + '" en Medellín' +
        '</div>'
      );
      searchDropdown.style.display = 'flex';
      return;
    }

    let html = '';
    results.slice(0, 6).forEach((item, index) => {
      const iconSvg = item.isIncident
        ? '<svg class="mapa-search-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
        : '<svg class="mapa-search-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>';

      html += (
        '<div class="mapa-search-item" data-index="' + index + '">' +
          iconSvg +
          '<div class="mapa-search-item-texts">' +
            '<span class="mapa-search-item-title">' + escapeHtml(item.name) + '</span>' +
            '<span class="mapa-search-item-sub">' + escapeHtml(item.sub) + '</span>' +
          '</div>' +
          '<span class="mapa-search-item-badge">' + escapeHtml(item.badge) + '</span>' +
        '</div>'
      );
    });

    searchDropdown.innerHTML = html;
    searchDropdown.style.display = 'flex';

    const items = searchDropdown.querySelectorAll('.mapa-search-item');
    items.forEach(el => {
      el.addEventListener('click', function () {
        const idx = parseInt(this.dataset.index, 10);
        const selected = results[idx];
        if (selected) {
          if (searchInput) searchInput.value = selected.name;
          goToAddressLocation(selected.name, selected.sub, selected.lat, selected.lng, selected.isIncident, selected.incidentData);
        }
      });
    });
  }

  // ── Eventos de Búsqueda ──
  if (searchInput) {
    // Al presionar Enter
    searchInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        triggerSearch(this.value);
      }
    });

    // Mientras escribe
    searchInput.addEventListener('input', function () {
      performLiveSuggestions(this.value);
    });

    // Cerrar dropdown al hacer clic fuera
    document.addEventListener('click', function (e) {
      if (!e.target.closest('#mapaSearchBox')) {
        if (searchDropdown) searchDropdown.style.display = 'none';
      }
    });
  }

  // Botón lupa de búsqueda
  if (searchBtn && searchInput) {
    searchBtn.addEventListener('click', function () {
      triggerSearch(searchInput.value);
    });
  }

  // Botón limpiar búsqueda
  if (searchClear) {
    searchClear.addEventListener('click', function () {
      if (searchInput) searchInput.value = '';
      if (searchDropdown) searchDropdown.style.display = 'none';
      this.style.display = 'none';
      searchTargetLayer.clearLayers();

      markersLayer.eachLayer(function (marker) {
        marker.setOpacity(1);
      });
    });
  }

  // ── Custom zoom controls ──
  var btnZoomIn = document.getElementById('btnZoomIn');
  var btnZoomOut = document.getElementById('btnZoomOut');
  var btnLocate = document.getElementById('btnLocate');

  if (btnZoomIn) {
    btnZoomIn.addEventListener('click', function () { map.zoomIn(); });
  }
  if (btnZoomOut) {
    btnZoomOut.addEventListener('click', function () { map.zoomOut(); });
  }
  if (btnLocate) {
    btnLocate.addEventListener('click', function () {
      if (!navigator.geolocation) {
        alert('Geolocalización no disponible en este navegador.');
        return;
      }
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          var latlng = [pos.coords.latitude, pos.coords.longitude];
          map.setView(latlng, 16);

          L.circle(latlng, {
            radius: 50,
            color: '#3b82f6',
            fillColor: '#3b82f6',
            fillOpacity: 0.25,
            weight: 2,
          }).addTo(map);

          L.circleMarker(latlng, {
            radius: 6,
            color: '#ffffff',
            fillColor: '#3b82f6',
            fillOpacity: 1,
            weight: 2,
          }).addTo(map);
        },
        function () {
          alert('No se pudo obtener tu ubicación.');
        }
      );
    });
  }

  // ── Carga inicial ──
  loadIncidents('TODOS');
})();
