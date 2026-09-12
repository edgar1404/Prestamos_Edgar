document.addEventListener('DOMContentLoaded', function() {
    // Escuchar el clic en los botones de editar por campo
    document.querySelectorAll('.btn-toggle-edit').forEach(function(button) {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            var targetId = this.getAttribute('data-target');
            var input = document.getElementById(targetId);
            
            if (input) {
                if (input.hasAttribute('readonly')) {
                    // Desbloquear campo
                    input.removeAttribute('readonly');
                    input.style.backgroundColor = '#ffffff';
                    input.focus();
                    this.classList.remove('btn-outline-primary');
                    this.classList.add('btn-warning');
                    this.innerHTML = '<i class="fas fa-lock-open mr-1"></i> Edición activa';
                } else {
                    // Bloquear campo
                    input.setAttribute('readonly', 'readonly');
                    input.style.backgroundColor = '#e9ecef';
                    this.classList.remove('btn-warning');
                    this.classList.add('btn-outline-primary');
                    this.innerHTML = '<i class="fas fa-pencil-alt mr-1"></i> Editar';
                }
            }
        });
    });
});