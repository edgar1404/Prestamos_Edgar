console.log("✅ Script custom_admin.js cargado correctamente.");

document.addEventListener('DOMContentLoaded', function () {

    // =========================================================================
    // 1. ESTILOS DEL DASHBOARD Y BARRA SUPERIOR
    // =========================================================================
    const bankStyles = document.createElement('style');
    bankStyles.innerHTML = `
        /* Barra de navegación superior */
        .main-header, .navbar, .navbar-white, .navbar-light {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%) !important;
            border-bottom: 1px solid #334155 !important;
            color: #ffffff !important;
        }
        .main-header .nav-link, .main-header .navbar-nav .nav-link, .main-header i, .main-header span {
            color: #f1f5f9 !important;
        }

        /* Fondo general */
        body.dashboard, .wrapper, .content-wrapper {
            background: linear-gradient(rgba(241, 245, 249, 0.75), rgba(241, 245, 249, 0.75)),
                        url('/static/admin/img/fondo.jpg') no-repeat center center fixed !important;
            background-size: cover !important;
        }

        /* Hero Banner */
        .bank-hero {
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.92) 0%, rgba(30, 41, 59, 0.88) 50%, rgba(15, 118, 110, 0.90) 100%),
                        url('/static/admin/img/fondo.jpg');
            background-blend-mode: overlay;
            background-size: cover;
            background-position: center;
            border-radius: 14px;
            padding: 24px 28px;
            color: #ffffff !important;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.25);
            margin-bottom: 25px;
            width: 100%;
        }
        .bank-hero h1 {
            font-size: 1.7rem;
            font-weight: 700;
            margin-bottom: 4px;
            color: #ffffff !important;
        }

        /* Tarjetas de KPIs */
        .kpi-card {
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 18px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.03);
            transition: transform 0.2s ease;
            height: 100%;
        }
        .kpi-card:hover { transform: translateY(-3px); }
        .kpi-title { font-size: 0.8rem; font-weight: 700; text-transform: uppercase; color: #64748b; }
        .kpi-value { font-size: 1.55rem; font-weight: 800; color: #0f172a; margin: 6px 0 2px 0; }
        .kpi-icon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; }

        /* Botones de Acción Rápida */
        .quick-action-btn {
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid #cbd5e1;
            border-radius: 10px;
            padding: 12px 15px;
            display: flex;
            align-items: center;
            gap: 10px;
            color: #0f172a;
            font-weight: 600;
            text-decoration: none !important;
            transition: all 0.2s ease;
        }
        .quick-action-btn:hover {
            background: #0284c7;
            color: #ffffff !important;
            border-color: #0284c7;
        }
        .quick-action-btn:hover i { color: #ffffff !important; }
    `;
    document.head.appendChild(bankStyles);

    // =========================================================================
    // 2. FUNCIÓN DE REEMPLAZO DEL DASHBOARD
    // =========================================================================
    function transformarDashboard() {
        const path = window.location.pathname;
        if (!(path === '/admin/' || path === '/admin' || path.endsWith('/admin/index.html'))) return;
        // Buscar el contenedor donde están las tarjetas viejas (Gestion, Autenticación, etc.)
        // Buscamos directamente la fila contenedora dentro de .content
        const appCards = document.querySelectorAll('.content .card');
        const parentRow = document.querySelector('.content .row');

        if (appCards.length > 0 && !document.querySelector('#custom-kpi-container')) {
            
            // Creamos el nuevo bloque del Dashboard
            const newDashboardHTML = `
                <div id="custom-kpi-container" class="col-12 col-lg-8">
                    <!-- KPIS FINANCIEROS -->
                    <div class="row mb-4">
                        <div class="col-md-4 col-sm-6 mb-3">
                            <div class="kpi-card d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="kpi-title">Cartera Activa</div>
                                    <div class="kpi-value">$128,450</div>
                                    <small class="text-success"><i class="fas fa-arrow-up mr-1"></i>+4.2% este mes</small>
                                </div>
                                <div class="kpi-icon" style="background: #e0f2fe; color: #0284c7;">
                                    <i class="fas fa-wallet"></i>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4 col-sm-6 mb-3">
                            <div class="kpi-card d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="kpi-title">Cobros del Día</div>
                                    <div class="kpi-value">$3,210</div>
                                    <small class="text-muted"><i class="fas fa-clock mr-1"></i>12 pagos hoy</small>
                                </div>
                                <div class="kpi-icon" style="background: #dcfce7; color: #16a34a;">
                                    <i class="fas fa-hand-holding-usd"></i>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-4 col-sm-6 mb-3">
                            <div class="kpi-card d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="kpi-title">Índice Mora</div>
                                    <div class="kpi-value">2.1%</div>
                                    <small class="text-danger"><i class="fas fa-exclamation-circle mr-1"></i>3 al cobro</small>
                                </div>
                                <div class="kpi-icon" style="background: #fee2e2; color: #dc2626;">
                                    <i class="fas fa-chart-line"></i>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- ACCIONES RÁPIDAS OPERATIVAS -->
                    <div class="card mb-4" style="background: rgba(255, 255, 255, 0.92) !important;">
                        <div class="card-header border-0 bg-transparent">
                            <h3 class="card-title font-weight-bold text-dark" style="font-size: 0.95rem;">
                                <i class="fas fa-bolt text-warning mr-2"></i>Acciones Rápidas Operativas
                            </h3>
                        </div>
                        <div class="card-body pt-0">
                            <div class="row">
                                <div class="col-md-3 col-6 mb-2">
                                    <a href="/admin/gestion/cliente/add/" class="quick-action-btn">
                                        <i class="fas fa-user-plus text-primary"></i>
                                        <span>Nuevo Cliente</span>
                                    </a>
                                </div>
                                <div class="col-md-3 col-6 mb-2">
                                    <a href="/admin/gestion/prestamo/add/" class="quick-action-btn">
                                        <i class="fas fa-file-invoice-dollar text-success"></i>
                                        <span>Nuevo Préstamo</span>
                                    </a>
                                </div>
                                <div class="col-md-3 col-6 mb-2">
                                    <a href="/admin/gestion/transaccion/add/" class="quick-action-btn">
                                        <i class="fas fa-receipt text-info"></i>
                                        <span>Registrar Pago</span>
                                    </a>
                                </div>
                                <div class="col-md-3 col-6 mb-2">
                                    <a href="/admin/gestion/prestamo/" class="quick-action-btn">
                                        <i class="fas fa-calculator text-warning"></i>
                                        <span>Ver Cartera</span>
                                    </a>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            // Ocultamos las tarjetas repetidas de modelos
            appCards.forEach(card => {
                // Si la tarjeta NO es del módulo "Acciones Recientes" (columna derecha), la ocultamos
                if (!card.closest('.col-lg-3') && !card.closest('.col-md-4') && !card.innerText.includes('Acciones recientes')) {
                    card.style.display = 'none';
                }
            });

            // Insertamos el nuevo panel al inicio de la fila principal
            if (parentRow) {
                parentRow.insertAdjacentHTML('afterbegin', newDashboardHTML);
            }
        }
    }

    // Ejecutar de inmediato y tras 300ms por si Jazzmin renderiza tarde
    transformarDashboard();
    setTimeout(transformarDashboard, 300);
});