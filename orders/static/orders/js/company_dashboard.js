function toggleSidebar() {
    document.getElementById('mainSidebar').classList.toggle('show');
    document.getElementById('sidebarOverlay').classList.toggle('show');
}

function openOSDetails(element) {
    const osNumber = element.dataset.os;
    const status = element.dataset.status;
    const origin = element.dataset.origin;
    const date = element.dataset.date;

    document.getElementById('modalOSNumber').innerText = osNumber;
    document.getElementById('modalOSStatus').innerText = status;
    document.getElementById('modalOSStatus').className = `status-badge status-${status.toUpperCase().replace(/ /g, '_')}`;
    document.getElementById('modalOSDate').innerText = `Criada em ${date}`;
    document.getElementById('modalOSOrigin').innerText = origin;
    document.getElementById('modalTimelineStatus').innerText = status;
    
    var modal = new bootstrap.Modal(document.getElementById('osDetailModal'));
    modal.show();
}

