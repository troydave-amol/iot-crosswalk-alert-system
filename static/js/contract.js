/**
 * @file contract.js
 * @description Defines the strict JSON Data Contract between Backend and Frontend.
 *              Includes Type Definitions (JSDoc), Validation, and Normalization.
 */

/**
 * @typedef {Object} StatusUpdatePayload
 * @property {string} timestamp_iso - ISO 8601 timestamp of the event (Required)
 * @property {string} [source] - "yolo" | "idle" | "backend" (Optional but recommended)
 * 
 * -- Detection & ROI --
 * @property {boolean} child_in_roi - True if child-class detected in ROI (Required)
 * @property {string} roi_status - "INSIDE" | "OUTSIDE" | "CHILD_IN_ROI" | "CLEAR" (Required)
 * @property {number} confidence - 0.0 to 1.0 (Required)
 * @property {number} latency_ms - Integer >= 0 (Required)
 * 
 * -- Warning Logic --
 * @property {boolean} [warning_logic_on] - Internal logic state. Derived from child_in_roi if absent
 * @property {boolean} [switch_enabled] - Physical/Software Master Switch state. Default: true
 * @property {boolean} warning_device_on - Final Output (Required)
 * 
 * -- Power System (Optional — hardware pending) --
 * @property {number} [battery_percent] - 0 to 100 (Optional, N/A if no hardware)
 * @property {string} [solar_status] - "Charging" | "Not charging" | "N/A" (Optional)
 * 
 * -- Optional --
 * @property {string} [scenario] - "Crowded" | "Low activity" | "Night" | "Rain" | "Normal" | "Live"
 * @property {string} [camera_status] - "OK" | "OFF" | "ERROR"
 * @property {string} [edge_status] - "OK" | "ERROR"
 * @property {string} [led_driver_status] - "Ready" | "Fault"
 */

/**
 * @typedef {Object} EventRow
 * @property {number} id - Unique Incrementing ID or Timestamp
 * @property {string} timestamp_iso - Source of Truth Time
 * @property {string} timestamp - Display Time (HH:MM:SS)
 * @property {boolean} child_in_roi
 * @property {string} roi_status
 * @property {number} confidence
 * @property {number} latency_ms
 * @property {boolean} warning_logic_on
 * @property {boolean} switch_enabled
 * @property {boolean} warning_device_on
 * @property {string} solar_status
 * @property {number} battery_percent
 * @property {string} [scenario]
 * @property {string} message - Safe display text
 * @property {boolean} false_warning - Derived analytic flag
 */

const DataContract = {

    /**
     * Validates the incoming payload against the strict contract.
     * @param {any} payload 
     * @returns {{ ok: boolean, errors: string[] }}
     */
    validateStatusUpdate: function (payload) {
        const errors = [];
        if (!payload || typeof payload !== 'object') {
            return { ok: false, errors: ['Payload is null or not an object'] };
        }

        // 1. Required Fields Existence & Type Checks
        const fastCheck = (key, type) => {
            if (payload[key] === undefined || payload[key] === null) errors.push(`Missing field: ${key}`);
            else if (typeof payload[key] !== type) errors.push(`Invalid type for ${key}: expected ${type}, got ${typeof payload[key]}`);
        };

        fastCheck('timestamp_iso', 'string');
        fastCheck('child_in_roi', 'boolean');
        fastCheck('roi_status', 'string');
        fastCheck('confidence', 'number');
        fastCheck('latency_ms', 'number');
        fastCheck('warning_device_on', 'boolean');
        // warning_logic_on, switch_enabled, battery_percent, solar_status are now optional

        if (errors.length > 0) return { ok: false, errors };

        // 2. Value Range & Enum Checks
        if (payload.confidence < 0 || payload.confidence > 1) errors.push(`Confidence out of range: ${payload.confidence}`);
        if (payload.latency_ms < 0) errors.push(`Latency must be >= 0`);
        if (typeof payload.battery_percent === 'number' && (payload.battery_percent < 0 || payload.battery_percent > 100)) {
            errors.push(`Battery must be 0-100`);
        }

        const validRoiStatus = ['INSIDE', 'OUTSIDE', 'CHILD_IN_ROI', 'CLEAR'];
        if (!validRoiStatus.includes(payload.roi_status)) errors.push(`Invalid roi_status: ${payload.roi_status}`);

        // Solar status validation (only if provided)
        if (payload.solar_status) {
            const validSolar = ['Charging', 'Not charging', 'N/A'];
            if (!validSolar.includes(payload.solar_status)) errors.push(`Invalid solar_status: ${payload.solar_status}`);
        }

        // 3. Logic & Contract Rules (only check if fields are present)
        if (payload.warning_logic_on !== undefined && payload.warning_logic_on !== payload.child_in_roi) {
            errors.push(`Contract Violation: warning_logic_on (${payload.warning_logic_on}) !== child_in_roi (${payload.child_in_roi})`);
        }

        // Rule 2: roi_status consistency (map both naming conventions)
        const isInsideStatus = payload.roi_status === 'INSIDE' || payload.roi_status === 'CHILD_IN_ROI';
        const isOutsideStatus = payload.roi_status === 'OUTSIDE' || payload.roi_status === 'CLEAR';
        if (payload.child_in_roi && isOutsideStatus) {
            errors.push(`Contract Violation: child_in_roi is TRUE but roi_status is ${payload.roi_status}`);
        }
        if (!payload.child_in_roi && isInsideStatus) {
            errors.push(`Contract Violation: child_in_roi is FALSE but roi_status is ${payload.roi_status}`);
        }

        // Rule 3: warning_device_on logic (only check if switch_enabled is present)
        if (payload.switch_enabled !== undefined) {
            const warnLogic = payload.warning_logic_on !== undefined ? payload.warning_logic_on : payload.child_in_roi;
            const expectedDeviceState = warnLogic && payload.switch_enabled;
            if (payload.warning_device_on !== expectedDeviceState) {
                errors.push(`Contract Violation: warning_device_on (${payload.warning_device_on}) does not match (logic && switch)`);
            }
        }

        return {
            ok: errors.length === 0,
            errors: errors
        };
    },

    /**
     * Normalizes a payload to ensure it is robust for the UI.
     * Fills defaults, fixes timestamps.
     * @param {any} raw 
     * @returns {StatusUpdatePayload}
     */
    normalizeStatusUpdate: function (raw) {
        // Fallback for completely broken input
        if (!raw || typeof raw !== 'object') raw = {};

        const now = new Date();

        // Ensure atomic flags are consistent if missing (defaults to safe state: OFF)
        const childIn = raw.child_in_roi === true;
        // If roi_status missing, derive from childIn
        const roiStat = raw.roi_status ? raw.roi_status : (childIn ? "INSIDE" : "OUTSIDE");

        // Logical state
        const warnLogic = raw.warning_logic_on !== undefined ? raw.warning_logic_on : childIn;
        const swEnabled = raw.switch_enabled !== undefined ? raw.switch_enabled : true; // Default switch ON

        // Device state
        const wDevice = (raw.warning_device_on !== undefined) ? raw.warning_device_on : (warnLogic && swEnabled);

        return {
            timestamp_iso: raw.timestamp_iso || now.toISOString(),
            source: raw.source || 'unknown',

            child_in_roi: childIn,
            roi_status: roiStat,
            confidence: (typeof raw.confidence === 'number') ? raw.confidence : 0.0,
            latency_ms: (typeof raw.latency_ms === 'number' && raw.latency_ms >= 0) ? Math.floor(raw.latency_ms) : 0,

            warning_logic_on: warnLogic,
            switch_enabled: swEnabled,
            warning_device_on: wDevice,

            battery_percent: (typeof raw.battery_percent === 'number') ? Math.max(0, Math.min(100, raw.battery_percent)) : 0,
            solar_status: raw.solar_status || 'N/A',

            // Optional / Passthrough
            scenario: raw.scenario || 'Normal',
            camera_status: raw.camera_status || 'OK',
            edge_status: raw.edge_status || 'OK',
            led_driver_status: raw.led_driver_status || 'Ready'
        };
    },

    /**
     * Builds a standardized EventRow for the logs/store.
     * @param {StatusUpdatePayload} payload 
     * @returns {EventRow}
     */
    buildEventRowFromStatus: function (payload) {
        const ts = new Date(payload.timestamp_iso);
        const timeStr = ts.toLocaleTimeString();

        // Safe Wording Logic
        let msg = "No child-class in ROI — Warning OFF";
        if (payload.warning_device_on) {
            msg = "Child-class in ROI — Warning ON";
        } else if (payload.child_in_roi && !payload.switch_enabled) {
            msg = "Child-class DETECTED — Warning DISABLED (Switch OFF)";
        }

        return {
            id: ts.getTime(), // Simple unique ID
            timestamp_iso: payload.timestamp_iso,
            timestamp: timeStr,

            child_in_roi: payload.child_in_roi,
            roi_status: payload.roi_status,
            confidence: payload.confidence,
            latency_ms: payload.latency_ms,

            warning_logic_on: payload.warning_logic_on,
            switch_enabled: payload.switch_enabled,
            warning_device_on: payload.warning_device_on,

            solar_status: payload.solar_status,
            battery_percent: payload.battery_percent,
            scenario: payload.scenario || 'Normal',

            message: msg,
            // Analytic flag: False Warning? 
            // "False Warning" usually means Warning ON but No Child. 
            // But per contract w_device MUST be false if no child. 
            // So false warning is impossible by logic unless sensor is wrong (which IS the child_in_roi flag).
            // Usually "False Positive" is what we track. If child_in_roi is TRUE but it's a ghost.
            // But we don't know ground truth here. 
            // However, existing dashboard had `false_warning: status.warning_on && !status.child_in_roi`.
            // In our contract, this state is forbidden. 
            // So false_warning in this derived context is always false unless we break contract.
            false_warning: (payload.warning_device_on && !payload.child_in_roi)
        };
    }

};

window.DataContract = DataContract;
