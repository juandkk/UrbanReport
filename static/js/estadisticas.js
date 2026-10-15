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

  function iniciar() {
    if (typeof Chart === 'undefined') return setTimeout(iniciar, 60);

    Chart.defaults.color = COLORS.texto;
    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";

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
          fill: true, tension: 0.35, pointRadius: 2,
        }]},
        options: { responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } } } },
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
        options: { responsive: true, maintainAspectRatio: false, cutout: '62%',
          plugins: { legend: { position: 'bottom', labels: { padding: 12, boxWidth: 12 } } } },
      });
    }

    // ---- Mis reportes por categoría: barras ----
    var catLabels = leer('m-cat-labels');
    var catData = leer('m-cat-data');
    var elCat = document.getElementById('chartMisCategorias');
    if (elCat && catLabels && catData) {
      new Chart(elCat, {
        type: 'bar',
        data: { labels: catLabels, datasets: [{
          label: 'Reportes', data: catData,
          backgroundColor: COLORS.azul, borderRadius: 6, maxBarThickness: 48,
        }]},
        options: { responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } } } },
      });
    }

    // ---- Mi actividad mensual: radicados vs resueltos ----
    var mesLabels = leer('m-mes-labels');
    var radData = leer('m-rad-data');
    var resData = leer('m-res-data');
    var elMes = document.getElementById('chartMisMeses');
    if (elMes && mesLabels) {
      new Chart(elMes, {
        type: 'line',
        data: { labels: mesLabels, datasets: [
          { label: 'Radicados', data: radData, borderColor: COLORS.morado,
            backgroundColor: 'rgba(139,92,246,0.12)', fill: true, tension: 0.35, pointRadius: 3 },
          { label: 'Solucionados', data: resData, borderColor: COLORS.verde,
            borderDash: [5, 4], fill: false, tension: 0.35, pointRadius: 3 },
        ]},
        options: { responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'top', labels: { boxWidth: 12, padding: 14 } } },
          scales: { x: { grid: { display: false } }, y: { beginAtZero: true, grid: { color: COLORS.grid }, ticks: { precision: 0 } } } },
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
