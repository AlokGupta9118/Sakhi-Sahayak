import { useCallback, useMemo, useState } from 'react';
import './SarthiRoutePanel.css';

/**
 * Usage:
 *   <SarthiRoutePanel
 *     tracker={tracker}                 // Existing useTracker() result
 *     location={location}               // Optional override
 *     onLocationChange={handleLocationChange} // Optional callback
 *   />
 *
 * This component intentionally uses the existing tracker API. It does not
 * create a second GPS watcher, socket connection, or microphone workflow.
 */
export default function SarthiRoutePanel({
  tracker,
  location: externalLocation,
  onLocationChange,
}) {
  // Hooks must run in the same order on every render. Do not return before hooks.
  const [showPrivacyInfo, setShowPrivacyInfo] = useState(false);
  const [actionError, setActionError] = useState('');

  const location = externalLocation ?? tracker?.location ?? null;
  const latitude = Number(location?.lat ?? location?.latitude);
  const longitude = Number(location?.lng ?? location?.lon ?? location?.longitude);

  const hasValidCoordinates =
    Number.isFinite(latitude) &&
    Number.isFinite(longitude) &&
    Math.abs(latitude) <= 90 &&
    Math.abs(longitude) <= 180;

  const isApproximate = Boolean(location?.isApproximate);
  const isLive = tracker?.locationStatus === 'live' &&
    hasValidCoordinates &&
    !isApproximate;

  const isActive = Boolean(tracker?.isSarthiActive);
  const micListening = tracker?.sarthiMicStatus === 'listening';
  const socketConnected = Boolean(tracker?.socketConnected);

  const statusLabel = useMemo(() => {
    if (isLive) return 'Live GPS';
    if (tracker?.locationStatus === 'denied') return 'Location permission denied';
    if (tracker?.locationStatus === 'unsupported') return 'GPS unavailable';
    if (isApproximate && hasValidCoordinates) return 'Approximate location';
    return 'Waiting for GPS';
  }, [isLive, tracker?.locationStatus, isApproximate, hasValidCoordinates]);

  const coordinatesLabel = isLive
    ? `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`
    : hasValidCoordinates
      ? `${latitude.toFixed(5)}, ${longitude.toFixed(5)} · not verified as live GPS`
      : 'Allow location access or enter a location in the trip planner.';

  const runAction = useCallback(async (action, fallbackMessage) => {
    setActionError('');
    if (typeof action !== 'function') {
      setActionError(fallbackMessage);
      return;
    }

    try {
      await action();
    } catch (error) {
      console.error('[SarthiRoutePanel] action failed:', error);
      setActionError(error?.message || fallbackMessage);
    }
  }, []);

  const handleToggleSarthi = () => {
    if (!tracker) return;

    const wasActive = Boolean(tracker.isSarthiActive);
    if (!wasActive && onLocationChange && location) {
      try {
        onLocationChange(location);
      } catch (error) {
        console.error('[SarthiRoutePanel] location callback failed:', error);
      }
    }

    runAction(
      tracker.toggleSarthiMode,
      'Sarthi mode is unavailable. Check the tracker setup.'
    );
  };

  const handleToggleMic = () => {
    runAction(
      tracker?.toggleSarthiMic,
      'Voice Guard is unavailable. Check the tracker setup.'
    );
  };

  const handleCancelAlarm = () => {
    runAction(
      tracker?.cancelSarthiAlarm,
      'Could not dismiss the safety check-in. Please try again.'
    );
  };

  const handleSOS = () => {
    runAction(
      typeof tracker?.triggerSOS === 'function'
        ? () => tracker.triggerSOS({ skipConfirm: true })
        : null,
      'SOS is unavailable. If you are in immediate danger in India, call 112.'
    );
  };

  if (!tracker) {
    return (
      <section className="sarthi-panel sarthi-panel--unavailable" aria-live="polite">
        <div className="sarthi-panel__brand">
          <span className="sarthi-panel__mark" aria-hidden="true">✦</span>
          <div>
            <p className="sarthi-panel__eyebrow">SAKHI–SAHAYAK</p>
            <h2>Sarthi <span>Safe Walk</span></h2>
            <p className="sarthi-panel__subtitle">
              The safety tracker is not connected to this panel yet.
            </p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section
      className={`sarthi-panel${isActive ? ' sarthi-panel--active' : ''}`}
      aria-labelledby="sarthi-panel-title"
    >
      <div className="sarthi-panel__top">
        <div className="sarthi-panel__brand">
          <span className="sarthi-panel__mark" aria-hidden="true">✦</span>
          <div>
            <p className="sarthi-panel__eyebrow">SAKHI–SAHAYAK</p>
            <h2 id="sarthi-panel-title">Sarthi <span>Safe Walk</span></h2>
            <p className="sarthi-panel__subtitle">
              Your journey, with an extra layer of care.
            </p>
          </div>
        </div>

        <span className={`sarthi-status${isActive ? ' is-on' : ''}`}>
          <i aria-hidden="true" />
          {isActive ? 'Protection on' : 'Standby'}
        </span>
      </div>

      <div className={`sarthi-location${isLive ? ' sarthi-location--live' : ''}`}>
        <div
          className={`sarthi-location__pulse${isLive ? ' is-live' : ''}`}
          aria-hidden="true"
        >
          <span />
          <span />
          <b>⌖</b>
        </div>

        <div className="sarthi-location__copy">
          <strong>{statusLabel}</strong>
          <span>{coordinatesLabel}</span>
        </div>

        <span
          className={`sarthi-location__dot${isLive ? ' is-live' : ''}`}
          aria-label={isLive ? 'GPS signal active' : 'GPS signal not confirmed'}
          title={isLive ? 'GPS signal active' : 'GPS signal not confirmed'}
        />
      </div>

      <button
        type="button"
        className={`sarthi-main-toggle${isActive ? ' is-enabled' : ''}`}
        onClick={handleToggleSarthi}
        aria-pressed={isActive}
      >
        <span className="sarthi-main-toggle__icon" aria-hidden="true">
          {isActive ? '✓' : '✦'}
        </span>
        <span className="sarthi-main-toggle__copy">
          <strong>{isActive ? 'Turn off Sarthi Mode' : 'Enable Sarthi Mode'}</strong>
          <small>
            {isActive
              ? 'Trip monitoring is currently enabled'
              : 'Start trip monitoring and safety check-ins'}
          </small>
        </span>
        <span className="sarthi-main-toggle__arrow" aria-hidden="true">→</span>
      </button>

      <div className="sarthi-features">
        <div className="sarthi-feature">
          <span className="sarthi-feature__icon" aria-hidden="true">⌖</span>
          <div className="sarthi-feature__copy">
            <strong>Live location</strong>
            <small>GPS updates while this page is open</small>
          </div>
          <span className={`sarthi-feature__state${isLive ? ' good' : ''}`}>
            {isLive ? 'Active' : 'Pending'}
          </span>
        </div>

        <div className="sarthi-feature">
          <span className="sarthi-feature__icon" aria-hidden="true">◉</span>
          <div className="sarthi-feature__copy">
            <strong>Safety check-ins</strong>
            <small>Movement prompts when Sarthi is enabled</small>
          </div>
          <span className={`sarthi-feature__state${isActive ? ' good' : ''}`}>
            {isActive ? 'On' : 'Off'}
          </span>
        </div>

        <div className="sarthi-feature sarthi-feature--voice">
          <span className="sarthi-feature__icon" aria-hidden="true">♫</span>
          <div className="sarthi-feature__copy">
            <strong>Voice Guard <em>Optional</em></strong>
            <small>Microphone is controlled separately</small>
          </div>
          <button
            type="button"
            className={`sarthi-voice-toggle${micListening ? ' is-on' : ''}`}
            onClick={handleToggleMic}
            aria-pressed={micListening}
          >
            {micListening ? 'Stop mic' : 'Enable mic'}
          </button>
        </div>
      </div>

      {tracker.isSarthiAlarm && (
        <div className="sarthi-alert" role="alert">
          <div className="sarthi-alert__symbol" aria-hidden="true">!</div>
          <div className="sarthi-alert__content">
            <strong>Safety check-in needed</strong>
            <p>If you are safe, confirm below. If you need help, use SOS.</p>
            <div className="sarthi-alert__actions">
              <button type="button" onClick={handleCancelAlarm}>I’m okay</button>
              <button
                type="button"
                className="sarthi-alert__sos"
                onClick={handleSOS}
              >
                Send SOS
              </button>
            </div>
          </div>
        </div>
      )}

      {tracker.voiceAnalysis?.distress_detected && (
        <div className="sarthi-alert sarthi-alert--voice" role="alert">
          <div className="sarthi-alert__symbol" aria-hidden="true">!</div>
          <div className="sarthi-alert__content">
            <strong>Possible distress signal detected</strong>
            <p>
              Voice detection can be wrong. Check the situation and use SOS if
              you need immediate help.
            </p>
          </div>
        </div>
      )}

      {actionError && (
        <p className="sarthi-action-error" role="alert">
          <strong>Action failed:</strong> {actionError}
        </p>
      )}

      <div className="sarthi-panel__footer">
        <span
          className={`sarthi-connection${socketConnected ? ' connected' : ''}`}
          aria-hidden="true"
        />
        <span>{socketConnected ? 'Safety service connected' : 'Safety service disconnected'}</span>
        <button
          type="button"
          onClick={() => setShowPrivacyInfo((value) => !value)}
          aria-expanded={showPrivacyInfo}
          aria-controls="sarthi-privacy-details"
        >
          {showPrivacyInfo ? 'Hide details' : 'Privacy & details'}
        </button>
      </div>

      {showPrivacyInfo && (
        <div className="sarthi-privacy" id="sarthi-privacy-details">
          <strong>Your controls matter</strong>
          <p>
            Sarthi uses the existing location and Socket.IO safety workflow.
            Voice Guard is optional and should request microphone access only
            when you enable it. When enabled, audio may be sent to the backend
            configured by your application.
          </p>
          <p>
            Keep this page open for the tracking workflow. Sarthi is not a
            replacement for emergency services. In India, call <strong>112</strong>
            if you are in immediate danger.
          </p>
        </div>
      )}
    </section>
  );
}
