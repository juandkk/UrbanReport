// =========================================================================
// Gestión de Incidentes - cambio de estado en línea (RF-005, Fase 2)
// =========================================================================
(function () {
  'use strict';

  function getCookie(name) {
    var v = null;
    if (document.cookie) {
      document.cookie.split(';').forEach(function (c) {
        var t = c.trim();
        if (t.indexOf(name + '=') === 0) v = decodeURIComponent(t.substring(name.length + 1));
      });
    }
    return v;
  }

  var toastEl = null;
  var toastTimer = null;
  function toast(msg, esError) {
    if (!toastEl) toastEl = document.getElementById('incToast');
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.className = 'inc-toast show' + (esError ? ' error' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.className = 'inc-toast'; }, 3000);
  }

  // Mantiene la clase de color del select sincronizada con el estado elegido.
  function aplicarColor(select) {
    select.classList.remove('inc-estado-reportado', 'inc-estado-en_proceso', 'inc-estado-resuelta');
    select.classList.add('inc-estado-' + select.value.toLowerCase());
  }

  function iniciar() {
    var selects = document.querySelectorAll('.inc-estado-select');
    selects.forEach(function (select) {
      select.addEventListener('change', function () {
        var postId = select.getAttribute('data-post-id');
        var anterior = select.getAttribute('data-estado-actual');
        var nuevo = select.value;
        if (nuevo === anterior) return;

        select.disabled = true;
        var body = new URLSearchParams();
        body.append('estado', nuevo);

        fetch('/feed/publicacion/' + postId + '/cambiar-estado/', {
          method: 'POST',
          headers: {
            'X-CSRFToken': getCookie('csrftoken'),
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: body.toString(),
        })
          .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
          .then(function (res) {
            if (res.ok && res.data.status === 'ok') {
              select.setAttribute('data-estado-actual', nuevo);
              aplicarColor(select);
              toast(res.data.message || 'Estado actualizado.');
            } else {
              // Revertir al estado anterior si el servidor rechazó el cambio
              select.value = anterior;
              aplicarColor(select);
              toast((res.data && res.data.message) || 'No se pudo actualizar el estado.', true);
            }
          })
          .catch(function () {
            select.value = anterior;
            aplicarColor(select);
            toast('Error de conexión al actualizar el estado.', true);
          })
          .finally(function () { select.disabled = false; });
      });
    });
  }

  // ---- Importación CSV (modal) ----
  function iniciarImportacion() {
    var modal = document.getElementById('importModal');
    var btnAbrir = document.getElementById('btnAbrirImportar');
    if (!modal || !btnAbrir) return;

    var btnCerrar = document.getElementById('btnCerrarImportar');
    var btnCancelar = document.getElementById('btnCancelarImportar');
    var form = document.getElementById('importForm');
    var input = document.getElementById('importFile');
    var fileLabel = document.getElementById('fileLabel');
    var fileDrop = document.getElementById('fileDrop');
    var btnEnviar = document.getElementById('btnEnviarImportar');
    var resultado = document.getElementById('importResult');

    function abrir() { modal.classList.add('open'); }
    function cerrar() { modal.classList.remove('open'); }

    btnAbrir.addEventListener('click', abrir);
    if (btnCerrar) btnCerrar.addEventListener('click', cerrar);
    if (btnCancelar) btnCancelar.addEventListener('click', cerrar);
    modal.addEventListener('click', function (e) { if (e.target === modal) cerrar(); });

    input.addEventListener('change', function () {
      if (input.files && input.files.length) {
        fileLabel.textContent = input.files[0].name;
        fileDrop.classList.add('has-file');
        btnEnviar.disabled = false;
      } else {
        fileLabel.textContent = 'Haz clic para elegir un archivo .csv';
        fileDrop.classList.remove('has-file');
        btnEnviar.disabled = true;
      }
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!input.files || !input.files.length) return;

      btnEnviar.disabled = true;
      btnEnviar.textContent = 'Importando…';
      resultado.hidden = true;

      var fd = new FormData(form);
      fetch('/feed/incidentes/importar/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCookie('csrftoken'), 'X-Requested-With': 'XMLHttpRequest' },
        body: fd,
      })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          var d = res.data;
          if (res.ok && d.status === 'ok') {
            var detalle = '';
            if (d.errores && d.errores.length) {
              detalle = '<ul class="inc-import-errors">';
              d.errores.slice(0, 10).forEach(function (er) {
                detalle += '<li>' + er.replace(/</g, '&lt;') + '</li>';
              });
              if (d.errores.length > 10) detalle += '<li>…y ' + (d.errores.length - 10) + ' más.</li>';
              detalle += '</ul>';
            }
            resultado.className = 'inc-import-result ok';
            resultado.innerHTML = '<strong>' + d.message + '</strong>' + detalle +
              '<div class="inc-import-reload">Recargando la tabla…</div>';
            resultado.hidden = false;
            toast(d.message);
            // Recargar para ver los nuevos reportes
            setTimeout(function () { window.location.reload(); }, 1600);
          } else {
            resultado.className = 'inc-import-result error';
            resultado.innerHTML = '<strong>' + ((d && d.message) || 'No se pudo importar.') + '</strong>';
            resultado.hidden = false;
            btnEnviar.disabled = false;
            btnEnviar.textContent = 'Importar';
          }
        })
        .catch(function () {
          resultado.className = 'inc-import-result error';
          resultado.textContent = 'Error de conexión al importar.';
          resultado.hidden = false;
          btnEnviar.disabled = false;
          btnEnviar.textContent = 'Importar';
        });
    });
  }

  function arrancar() {
    iniciar();
    iniciarImportacion();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', arrancar);
  } else {
    arrancar();
  }
})();
