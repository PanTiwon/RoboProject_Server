<script>
(function(){
  'use strict';

  // ==========================================
  // 1. HELPERS & CONSTANTS
  // ==========================================
  const $ = (id) => document.getElementById(id);
  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const pad2 = (n) => String(n).padStart(2, '0');

  // Visualization Colors
  const COL_FWD = '#4ade80'; // Clear Green for Forward
  const COL_REV = '#f87171'; // Clear Red for Reverse
  const COL_IDLE = '#4b5563'; // Gray for Idle/No Signal

  // ==========================================
  // 2. STATE VARIABLES
  // ==========================================
  const nodes = {
    controller: { online: false, since: Date.now() },
    pi:         { online: false, since: Date.now() },
    esp:        { online: false, since: Date.now() },
    motors:     { online: false, since: Date.now() }
  };

  // Sub-component statuses (driven by WebSocket and/or HTTP poll)
  let cameraOnline = false;
  let sweeperOnline = false;
  
  const links = [
    ['controller-pi', 'controller', 'pi'],
    ['pi-esp', 'pi', 'esp'],
    ['esp-motors', 'esp', 'motors']
  ];

  // System Telemetry (Targets updated via WebSocket)
  let cpuLoad = 0, cpuLoadTarget = 0;
  let cpuTemp = 0, cpuTempTarget = 0;
  let ram = 0, ramTarget = 0;

  // Joystick & Movement Targets (Received via WebSocket)
  let joyX = 0, joyY = 0, joyW = 0;
  let joyXTarget = 0, joyYTarget = 0, joyWTarget = 0;

  // Wheel Speeds & Targets (Received via WebSocket from Pi Kinematics)
  let wheelFL = 0, wheelFR = 0, wheelBL = 0, wheelBR = 0;
  let wheelFLTarget = 0, wheelFRTarget = 0, wheelBLTarget = 0, wheelBRTarget = 0;

  let paused = false;
  let currentMode = 'unknown'; // 'manual' | 'demo' | 'auto' | 'unknown'
  const startTime = Date.now();

  const GAUGE_C = 2 * Math.PI * 42;
  ['arcCpuLoad', 'arcCpuTemp', 'arcRam'].forEach(id => {
    const el = $(id);
    if(el) {
      el.style.strokeDasharray = GAUGE_C.toFixed(2);
      el.style.strokeDashoffset = GAUGE_C.toFixed(2);
    }
  });

  // ==========================================
  // 3. LOGGING SYSTEM
  // ==========================================
  function timeStr(d){
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }

  function pushLog(msg, level){
    const body = $('logBody');
    if(!body) return;
    const line = document.createElement('div');
    line.className = 'log-line ' + (level || 'info');
    line.innerHTML = `<span class="log-time">[${timeStr(new Date())}]</span> <span class="log-msg">${msg}</span>`;
    body.appendChild(line);
    while(body.children.length > 40){ body.removeChild(body.firstChild); }
    body.scrollTop = body.scrollHeight;
  }

  pushLog('Dashboard initialized. Awaiting WebSocket connection...', 'info');

  // ==========================================
  // 3.5  SYSTEM MODE DISPLAY
  // ==========================================
  // Maps raw WebSocket/HTTP values → display label + CSS class.
  // "LIVE" is treated as an alias for "Manual" per spec.
  //
  //  Raw value │ Display │ CSS class
  //  ──────────┼─────────┼───────────
  //  "LIVE"    │ MANUAL  │ mode-manual   (teal)
  //  "Manual"  │ MANUAL  │ mode-manual   (teal)
  //  "Demo"    │ DEMO    │ mode-demo     (amber)
  //  "Auto"    │ AUTO    │ mode-auto     (purple)
  //  other/null│  —      │ mode-unknown  (dim)
  //
  function updateModeDisplay(rawMode){
    const badge = $('modeBadge');
    const label = $('modeValue');
    if(!badge || !label) return;

    // Normalise: LIVE → Manual, then lowercase for switch
    const raw    = (rawMode || '').trim();
    const mapped = raw.toUpperCase() === 'LIVE' ? 'Manual' : raw;
    const key    = mapped.toLowerCase();

    // Strip all mode state classes
    badge.classList.remove('mode-manual', 'mode-demo', 'mode-auto', 'mode-unknown');

    switch(key){
      case 'manual':
        badge.classList.add('mode-manual');
        label.textContent = 'MANUAL';
        currentMode = 'manual';
        break;
      case 'demo':
        badge.classList.add('mode-demo');
        label.textContent = 'DEMO';
        currentMode = 'demo';
        break;
      case 'auto':
        badge.classList.add('mode-auto');
        label.textContent = 'AUTO';
        currentMode = 'auto';
        break;
      default:
        badge.classList.add('mode-unknown');
        label.textContent = '—';
        currentMode = 'unknown';
    }
  }

  // ==========================================
  // 4. UI UPDATERS (Gauges & Topology)
  // ==========================================
  function classify(value, warnAt, critAt){
    if(value >= critAt) return 'crit';
    if(value >= warnAt) return 'warn';
    return 'normal';
  }

  function gaugeColor(state){
    if(state === 'crit') return '#ff4d4f';
    if(state === 'warn') return '#ffb300';
    return '#2fe0c8';
  }

  function setGauge(arcId, numId, value, unit, min, max, warnAt, critAt, decimals){
    const el = $(arcId);
    const numEl = $(numId);
    if(!el || !numEl) return;
    
    const pct = clamp((value - min) / (max - min), 0, 1);
    el.style.strokeDashoffset = (GAUGE_C * (1 - pct)).toFixed(2);
    
    const state = classify(value, warnAt, critAt);
    el.style.stroke = gaugeColor(state);
    numEl.textContent = decimals ? value.toFixed(decimals) : Math.round(value);
  }

  function updateTopologyDom(){
    Object.keys(nodes).forEach(name => {
      const el = document.querySelector(`.node[data-node="${name}"]`);
      if(el){
        el.classList.toggle('offline', !nodes[name].online);
        el.querySelector('.badge-text').textContent = nodes[name].online ? 'ONLINE' : 'OFFLINE';
      }
    });

    links.forEach(([id, a, b]) => {
      const el = document.querySelector(`.link[data-link="${id}"]`);
      if(el) el.classList.toggle('broken', !(nodes[a].online && nodes[b].online));
    });

    const allOnline = Object.values(nodes).every(n => n.online);
    const chip = $('systemChip');
    if(chip) {
      chip.classList.toggle('degraded', !allOnline);
      $('systemChipText').textContent = allOnline ? 'SYSTEM NOMINAL' : 'LINK DEGRADED';
    }

    // Cascading availability check
    const piReachable = nodes.pi.online;
    const espReachable = piReachable && nodes.esp.online;
    const motorsReachable = espReachable && nodes.motors.online;

    if($('piPanel')) $('piPanel').classList.toggle('no-signal', !piReachable);
    if($('movementPanel')) $('movementPanel').classList.toggle('no-signal', !piReachable);
    if($('chassis')) $('chassis').classList.toggle('no-signal', !motorsReachable);

    // --- Sub-status: Camera (only online if Pi itself is online) ---
    const effectiveCameraOnline = cameraOnline && piReachable;
    const camBadge = $('cameraSubBadge');
    const camText  = $('cameraStatus');
    if(camBadge && camText){
      camBadge.classList.toggle('online', effectiveCameraOnline);
      camText.textContent = effectiveCameraOnline ? 'ONLINE' : 'OFFLINE';
    }

    // --- Sub-status: Sweeper (only online if ESP32 itself is online) ---
    const effectiveSweeperOnline = sweeperOnline && espReachable;
    const swpBadge = $('sweeperSubBadge');
    const swpText  = $('sweeperStatus');
    if(swpBadge && swpText){
      swpBadge.classList.toggle('online', effectiveSweeperOnline);
      swpText.textContent = effectiveSweeperOnline ? 'ONLINE' : 'OFFLINE';
    }

    return { piReachable, espReachable, motorsReachable };
  }

  // ==========================================
  // 5. IMPROVED WHEEL VISUALIZATION
  // ==========================================
  // Enhancements:
  // 1. Explicit directional arrows (▲ / ▼) are injected directly into the HTML.
  // 2. Strict Red/Green color coding (Forward = Green, Reverse = Red).
  // 3. Clear percentages replacing arbitrary float values.
  // 4. Fallbacks to Gray/Idle state when speed is ~0 or connection drops.
  function applyWheel(drumId, ringId, speedId, speed, signalOk){
    const ring = $(ringId);
    const label = $(speedId);
    const drum = $(drumId);
    
    if(!ring || !label || !drum) return;

    drum.classList.toggle('no-signal', !signalOk);
    drum.classList.remove('fwd-glow', 'rev-glow');

    if(!signalOk){
      ring.style.animation = 'none';
      ring.style.borderColor = COL_IDLE;
      label.innerHTML = '&#9644; NO SIGNAL';
      label.style.color = '#9ca3af';
      return;
    }

    const mag = Math.abs(speed);
    const pct = Math.round(mag * 100);

    if(mag < 0.02){
      ring.style.animation = 'none';
      ring.style.borderColor = COL_IDLE;
      label.innerHTML = '&#9644; IDLE';
      label.style.color = '#9ca3af';
      return;
    }

    const forward = speed >= 0;
    const duration = clamp(2.1 - mag * 1.85, 0.28, 2.1).toFixed(2);
    const dir = forward ? 'spin-cw' : 'spin-ccw';

    // Apply colors and animations
    ring.style.borderColor = forward ? COL_FWD : COL_REV;
    ring.style.animation = `${dir} ${duration}s linear infinite`;

    // Apply Arrow and Percentage Text
    label.innerHTML = (forward ? '&#9650; FWD ' : '&#9660; REV ') + pct + '%';
    label.style.color = forward ? COL_FWD : COL_REV;

    drum.classList.add(forward ? 'fwd-glow' : 'rev-glow');
  }

  // ==========================================
  // 6. WEBSOCKET HANDLER 
  // ==========================================
  const WS_URL = 'wss://core.tailb47df1.ts.net:8080';
  let ws;

  function connectWebSocket(){
    ws = new WebSocket(WS_URL);
    
    ws.onopen = () => {
      pushLog('WebSocket connected to Raspberry Pi', 'ok');
      // Mark system components as online based on WebSocket success
      Object.keys(nodes).forEach(n => nodes[n].online = true);
    };
    
    ws.onmessage = (event) => {
      if(paused) return; // Ignore data if UI is paused

      let data;
      try { data = JSON.parse(event.data); } 
      catch(e) { console.error('Malformed telemetry payload:', e); return; }

      // 6.1 Parse System Status & Mode
      if(data.status){
        nodes.pi.online         = (data.status.pi         === "Online");
        nodes.esp.online        = (data.status.esp32      === "Online");
        nodes.motors.online     = (data.status.motor      === "Online");
        nodes.controller.online = (data.status.controller === "Online");

        // Parse sub-component statuses
        cameraOnline  = (data.status.camera  === "Online");
        sweeperOnline = (data.status.sweeper === "Online");

        // DEMO OVERRIDE: If we are in DEMO mode, fake the ESP32/Motors to Online 
        // so the UI allows the wheels to spin visually!
        if (data.status.mode === "DEMO") {
            nodes.esp.online  = true;
            nodes.motors.online = true;
        }

        // Update the System Mode badge in real-time
        if(data.status.mode !== undefined){
          updateModeDisplay(data.status.mode);
        }
      }

      // 6.2 Parse Movement Payload
      if(data.movement){
        joyXTarget = clamp(data.movement.joy_x ?? 0, -1, 1);
        joyYTarget = clamp(data.movement.joy_y ?? 0, -1, 1);
        joyWTarget = clamp(data.movement.joy_w ?? 0, -1, 1);
        
        // Parse Wheel Payload (It is inside data.movement.wheels)
        // Note: Python sends 0-255. We divide by 255 to map to 0.0 - 1.0 for the UI
        if(data.movement.wheels){
          wheelFLTarget = clamp((data.movement.wheels.fl ?? 0) / 255, -1, 1);
          wheelFRTarget = clamp((data.movement.wheels.fr ?? 0) / 255, -1, 1);
          wheelBLTarget = clamp((data.movement.wheels.bl ?? 0) / 255, -1, 1);
          wheelBRTarget = clamp((data.movement.wheels.br ?? 0) / 255, -1, 1);
        }
      }

      // 6.3 Parse System Telemetry
      if(data.telemetry) {
        cpuLoadTarget = data.telemetry.cpu_load ?? cpuLoadTarget;
        ramTarget = data.telemetry.ram_usage ?? ramTarget;
        cpuTempTarget = data.telemetry.cpu_temp ?? cpuTempTarget;
      }
    };
    
    ws.onclose = () => {
      pushLog('WebSocket connection lost — Retrying in 3s...', 'warn');
      // Drop nodes to offline state
      Object.keys(nodes).forEach(n => nodes[n].online = false);
      // Reset mode badge — will be restored by HTTP poll or on reconnect
      updateModeDisplay(null);
      
      // Zero out all targets for safety
      joyXTarget = joyYTarget = joyWTarget = 0;
      wheelFLTarget = wheelFRTarget = wheelBLTarget = wheelBRTarget = 0;
      
      setTimeout(connectWebSocket, 3000);
    };
    
    ws.onerror = () => ws.close();
  }

  // Init Connection
  connectWebSocket();

  // ==========================================
  // 6.5  HTTP STATUS POLL  (Fetch API)
  // ==========================================
  //
  // Expected JSON payload from /api/status on your Python/C++ backend:
  //
  //  {
  //    "status": {
  //      "controller": "Online",   // "Online" | "Offline"
  //      "pi":         "Online",   // "Online" | "Offline"
  //      "esp32":      "Online",   // "Online" | "Offline"
  //      "motor":      "Online",   // "Online" | "Offline"
  //      "camera":     "Online",   // "Online" | "Offline"  ← NEW
  //      "sweeper":    "Offline",  // "Online" | "Offline"  ← NEW
  //      "mode":       "LIVE"      // "LIVE"   | "DEMO"
  //    }
  //  }
  //
  // The Fetch poll runs every 3 s and acts as a heartbeat / fallback for
  // status data.  Live telemetry (movement, wheels, gauges) is still
  // delivered over WebSocket for low latency.
  //
  function fetchStatus(){
    fetch('https://core.tailb47df1.ts.net:8080/api/status')
      .then(function(res){
        if(!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function(data){
        if(!data.status) return;

        // Update main node reachability
        nodes.controller.online = (data.status.controller === "Online");
        nodes.pi.online         = (data.status.pi         === "Online");
        nodes.esp.online        = (data.status.esp32      === "Online");
        nodes.motors.online     = (data.status.motor      === "Online");

        // Update sub-component statuses
        cameraOnline  = (data.status.camera  === "Online");
        sweeperOnline = (data.status.sweeper === "Online");

        // DEMO mode override (mirrors WebSocket logic)
        if(data.status.mode === "DEMO"){
          nodes.esp.online    = true;
          nodes.motors.online = true;
        }

        // Update System Mode badge from poll (acts as fallback if WS is silent)
        if(data.status.mode !== undefined){
          updateModeDisplay(data.status.mode);
        }

        pushLog('Status poll OK — cam:' + (cameraOnline ? 'ON' : 'OFF') + ' sweep:' + (sweeperOnline ? 'ON' : 'OFF'), 'info');
      })
      .catch(function(err){
        pushLog('Status poll error: ' + err.message, 'warn');
      });
  }

  // Poll immediately on load, then every 3 seconds
  fetchStatus();
  setInterval(fetchStatus, 3000);

  // ==========================================
  // 7. RENDER LOOPS
  // ==========================================
  
  function movementTick(avail){
    // Fail-safe: Zero out targets visually if unreachable
    if(!avail.piReachable) {
      joyXTarget = 0; joyYTarget = 0; joyWTarget = 0;
    }
    if(!avail.motorsReachable) {
      wheelFLTarget = 0; wheelFRTarget = 0; wheelBLTarget = 0; wheelBRTarget = 0;
    }

    // Smooth interpolation (lerp) towards target data
    joyX = lerp(joyX, joyXTarget, 0.08);
    joyY = lerp(joyY, joyYTarget, 0.08);
    joyW = lerp(joyW, joyWTarget, 0.08);

    wheelFL = lerp(wheelFL, wheelFLTarget, 0.12);
    wheelFR = lerp(wheelFR, wheelFRTarget, 0.12);
    wheelBL = lerp(wheelBL, wheelBLTarget, 0.12);
    wheelBR = lerp(wheelBR, wheelBRTarget, 0.12);

    // Update Radar UI
    if($('radarDot') && $('radarVector')) {
      const px = 100 + joyX * 80;
      const py = 100 - joyY * 80;
      $('radarDot').setAttribute('cx', px.toFixed(1));
      $('radarDot').setAttribute('cy', py.toFixed(1));
      $('radarVector').setAttribute('x2', px.toFixed(1));
      $('radarVector').setAttribute('y2', py.toFixed(1));
    }

    const speedMag = clamp(Math.sqrt(joyX*joyX + joyY*joyY), 0, 1);
    const headingDeg = ((Math.atan2(joyX, joyY) * 180 / Math.PI) + 360) % 360;

    if($('valX')) $('valX').textContent = joyX.toFixed(2);
    if($('valY')) $('valY').textContent = joyY.toFixed(2);
    if($('valRot')) $('valRot').textContent = joyW.toFixed(2);
    if($('valHeading')) $('valHeading').textContent = (avail.piReachable ? String(Math.round(headingDeg)).padStart(3,'0')+'°' : '---°');
    if($('valSpeed')) $('valSpeed').textContent = (avail.piReachable ? Math.round(speedMag*100) : 0) + '%';
    if($('valMode')) $('valMode').textContent = !avail.piReachable ? 'NO LINK' : (speedMag < 0.06 && Math.abs(joyW) < 0.06 ? 'HOLD' : 'DRIVE');

    const arrow = $('headingArrow');
    if(arrow) {
      arrow.style.transform = avail.motorsReachable ? `rotate(${headingDeg}deg) scale(${0.85 + speedMag * 0.4})` : 'rotate(0deg) scale(0.7)';
      arrow.style.opacity = avail.motorsReachable ? Math.min(1, 0.5 + speedMag) : 0.25;
    }

    // Update Wheel UI
    applyWheel('drumFL','ringFL','speedFL', wheelFL, avail.motorsReachable);
    applyWheel('drumFR','ringFR','speedFR', wheelFR, avail.motorsReachable);
    applyWheel('drumBL','ringBL','speedBL', wheelBL, avail.motorsReachable);
    applyWheel('drumBR','ringBR','speedBR', wheelBR, avail.motorsReachable);
  }

  function telemetryTick(avail){
    if(avail.piReachable){
      cpuLoad = lerp(cpuLoad, cpuLoadTarget, 0.05);
      cpuTemp = lerp(cpuTemp, cpuTempTarget, 0.05);
      ram = lerp(ram, ramTarget, 0.05);

      setGauge('arcCpuLoad','numCpuLoad', cpuLoad, '%', 0, 100, 70, 88, 0);
      setGauge('arcCpuTemp','numCpuTemp', cpuTemp, '°C', 35, 85, 65, 75, 0);
      setGauge('arcRam','numRam', ram, '%', 0, 100, 70, 85, 0);
      
      if($('cpuClock')) $('cpuClock').textContent = (1.2 + (cpuLoad/100)*0.6).toFixed(1) + 'GHz';
      if($('procCount')) $('procCount').textContent = Math.round(118 + cpuLoad*0.6);
    }
  }

  function frame(){
    const avail = updateTopologyDom();
    
    if(!paused){
      telemetryTick(avail);
      movementTick(avail);
    }

    // Clocks
    const upSec = Math.floor((Date.now() - startTime) / 1000);
    const h = pad2(Math.floor(upSec / 3600));
    const m = pad2(Math.floor((upSec % 3600) / 60));
    const s = pad2(upSec % 60);
    if($('uptimeValue')) $('uptimeValue').textContent = h+':'+m+':'+s;
    if($('clockValue')) $('clockValue').textContent = timeStr(new Date());

    requestAnimationFrame(frame);
  }

  // Start Core Loop
  requestAnimationFrame(frame);

  // ==========================================
  // 8. EVENT LISTENERS
  // ==========================================
  if($('pauseBtn')) {
    $('pauseBtn').addEventListener('click', function(){
      paused = !paused;
      this.innerHTML = paused
        ? '<i class="fa-solid fa-play"></i> RESUME FEED'
        : '<i class="fa-solid fa-pause"></i> PAUSE FEED';
      pushLog(paused ? 'Telemetry feed paused by operator' : 'Telemetry feed resumed', 'info');
    });
  }

  // Fault simulation button is intentionally removed as this is now a production interface.
  if($('faultBtn')) {
    $('faultBtn').style.display = 'none'; 
  }

  // Initial DOM pass
  updateTopologyDom();

})();
</script>