// =========================================================================
// Estadísticas (RF-006, RF-020) - gráficas con Chart.js
// =========================================================================
(function () {
  'use strict';

  function leer(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  var COLORS = {
    azul: '#3b82f6',
    verde: '#22c55e',
    ambar: '#f59e0b',
    gris: '#94a3b8',
    morado: '#8b5cf6',
    grid: 'rgba(148, 163, 184, 0.12)',
    texto: '#94a3b8',
  };

  function abreviarEtiqueta(label) {
    var mapa = {
      'Redes eléctricas y telecomunicaciones': 'Redes y Telecom.',
      'Aseo y basuras': 'Aseo y Basuras',
      'Infraestructura': 'Infraestruct.',
    };
    return mapa[label] || label;
  }

  function iniciar() {
    if (typeof Chart === 'undefined') return setTimeout(iniciar, 60);

    var esMovil = window.innerWidth <= 640;
    Chart.defaults.color = COLORS.texto;
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.font.size = esMovil ? 11 : 12;

    // ---- Tendencia general (admin) ----
    var tendLabels = leer('g-tend-labels');
    var tendData = leer('g-tend-data');
    var elTend = document.getElementById('chartTendencia');
    if (elTend && tendLabels && tendData) {
      new Chart(elTend, {
        type: 'line',
        data: { labels: tendLabels, datasets: [{
          label: 'Reportes', data: tendData,
          borderColor: COLORS.azul, backgroundColor: 'rgba(59,130,246,0.15)',
          fill: true, tension: 0.35, pointRadius: esMovil ? 2 : 3,
        }]},
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: {
              grid: { display: false },
              ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: esMovil ? 6 : 14 },
            },
            y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } },
          },
        },
      });
    }

    // ---- Resumen de estado (admin): dona ----
    var estLabels = leer('g-est-labels');
    var estData = leer('g-est-data');
    var elEst = document.getElementById('chartEstado');
    if (elEst && estLabels && estData) {
      new Chart(elEst, {
        type: 'doughnut',
        data: { labels: estLabels, datasets: [{
          data: estData,
          // Reportado=gris, En Proceso=amarillo, Resuelta=verde (igual que el mapa)
          backgroundColor: [COLORS.gris, COLORS.ambar, COLORS.verde],
          borderColor: '#0f172a', borderWidth: 2,
        }]},
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '62%',
          plugins: {
            legend: {
              position: 'bottom',
              labels: { padding: esMovil ? 10 : 12, boxWidth: esMovil ? 10 : 12, font: { size: esMovil ? 11 : 12 } },
            },
          },
        },
      });
    }

    // ---- Mis reportes por categoría: barras (horizontales en móvil para que las 7 etiquetas se lean completas) ----
    var catLabels = leer('m-cat-labels');
    var catData = leer('m-cat-data');
    var elCat = document.getElementById('chartMisCategorias');
    if (elCat && catLabels && catData) {
      var catLabelsCortas = catLabels.map(abreviarEtiqueta);
      new Chart(elCat, {
        type: 'bar',
        data: { labels: catLabelsCortas, datasets: [{
          label: 'Reportes', data: catData,
          backgroundColor: COLORS.azul, borderRadius: 6, maxBarThickness: esMovil ? 22 : 44,
        }]},
        options: {
          indexAxis: esMovil ? 'y' : 'x',
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: esMovil ? {
            x: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } },
            y: { grid: { display: false }, ticks: { autoSkip: false, font: { size: 11 } } },
          } : {
            x: { grid: { display: false }, ticks: { maxRotation: 25, minRotation: 0, autoSkip: false, font: { size: 11 } } },
            y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } },
          },
        },
      });
    }

    // ---- Mi actividad mensual: radicados vs resueltos ----
    var mesLabels = leer('m-mes-labels');
    var radData = leer('m-rad-data');
    var resData = leer('m-res-data');
    var elMes = document.getElementById('chartMisMeses');
    if (elMes && mesLabels) {
      var chartMeses = new Chart(elMes, {
        type: 'line',
        data: { labels: mesLabels, datasets: [
          { label: 'Radicados', data: radData, borderColor: COLORS.morado,
            backgroundColor: COLORS.morado, pointBackgroundColor: COLORS.morado,
            fill: false, tension: 0.35, pointRadius: 3 },
          { label: 'Solucionados', data: resData, borderColor: COLORS.verde,
            backgroundColor: COLORS.verde, pointBackgroundColor: COLORS.verde,
            borderDash: [5, 4], fill: false, tension: 0.35, pointRadius: 3 },
        ]},
        options: {
          responsive: true,
          maintainAspectRatio: false,
          // Leyenda nativa desactivada: usamos la leyenda HTML con checkboxes.
          plugins: { legend: { display: false } },
          scales: {
            x: {
              grid: { display: false },
              ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: esMovil ? 6 : 12 },
            },
            y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } },
          },
        },
      });

      // Conecta los checkboxes de la leyenda personalizada con la visibilidad
      // de cada serie del gráfico.
      var checks = document.querySelectorAll('#mesesLegend .stats-legend-check');
      checks.forEach(function (chk) {
        chk.addEventListener('change', function () {
          var idx = parseInt(chk.getAttribute('data-ds'), 10);
          chartMeses.setDatasetVisibility(idx, chk.checked);
          chartMeses.update();
          // Atenúa visualmente la etiqueta cuando la serie está oculta
          var item = chk.closest('.stats-legend-item');
          if (item) item.classList.toggle('is-off', !chk.checked);
        });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
