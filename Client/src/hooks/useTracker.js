
import { useCallback, useEffect, useRef, useState } from 'react';
import { socket } from '../lib/socket';
import { api, getApiError } from '../lib/api';

const NAGPUR = {
  lat: 21.1458,
  lng: 79.0882,
};

function distanceMeters(a, b) {
  const rad = (value) => (value * Math.PI) / 180;

  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);

  const x =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) *
      Math.cos(rad(b.lat)) *
      Math.sin(dLng / 2) ** 2;

  return (
    6371000 *
    2 *
    Math.atan2(
      Math.sqrt(x),
      Math.sqrt(Math.max(0, 1 - x))
    )
  );
}

function getUserName(user) {
  return user?.name || user?.userName || 'Traveler';
}

function getUserPhone(user) {
  return user?.phone || user?.userPhone || '';
}

function getUserEmergencyEmail(user) {
  return user?.emergency_email || user?.emergencyEmail || '';
}

function getUserEmergencyPhone(user) {
  return user?.emergency_phone || user?.emergencyPhone || '';
}

function getUserEmergencyName(user) {
  return user?.emergency_name || user?.emergencyName || '';
}

export function useTracker(user = {}) {
  const [location, setLocation] = useState({
    ...NAGPUR,
    isApproximate: true,
  });

  const [locationStatus, setLocationStatus] = useState(
    typeof navigator !== 'undefined' &&
      'geolocation' in navigator
      ? 'requesting'
      : 'unsupported'
  );

  const [socketConnected, setSocketConnected] = useState(
    socket.connected
  );

  const [isSarthiActive, setIsSarthiActive] = useState(false);
  const [isSarthiAlarm, setIsSarthiAlarm] = useState(false);
  const [isSOS, setIsSOS] = useState(false);

  const [agentState, setAgentState] = useState({
    status: 'IDLE',
  });

  const [voiceAnalysis, setVoiceAnalysis] = useState(null);
  const [lastMovedTime, setLastMovedTime] = useState(0);
  const [sarthiMicStatus, setSarthiMicStatus] = useState('off');

  const lastLocationRef = useRef(null);
  const alarmRef = useRef(false);
  const sosRef = useRef(false);
  const userRef = useRef(user);
  const locationRef = useRef(location);

  const sarthiStreamRef = useRef(null);
  const sarthiRecorderRef = useRef(null);
  const sarthiChunkTimerRef = useRef(null);
  const sarthiUploadBusyRef = useRef(false);
  const sarthiActiveRef = useRef(false);

  useEffect(() => {
    userRef.current = user;
  }, [user]);

  useEffect(() => {
    locationRef.current = location;
  }, [location]);

  // Keep the location ref updated immediately when GPS changes.
  const updateLocation = useCallback((nextLocation) => {
    locationRef.current = nextLocation;
    setLocation(nextLocation);
  }, []);

  // --------------------------------------------------
  // SOCKET.IO CONNECTION AND BACKEND EVENTS
  // --------------------------------------------------

  useEffect(() => {
    const onConnect = () => setSocketConnected(true);
    const onDisconnect = () => setSocketConnected(false);

    const onAgentState = (payload = {}) => {
      setAgentState((previous) => ({
        ...previous,
        ...payload,
      }));

      if (
        [
          'EMERGENCY_PROTOCOL',
          'RECORDING',
          'THREAT_DETECTED',
          'INTERCEPT_COUNTDOWN',
        ].includes(payload.status)
      ) {
        sosRef.current = true;
        setIsSOS(true);
      }

      if (
        ['RESOLVED', 'MONITORING', 'IDLE'].includes(
          payload.status
        )
      ) {
        sosRef.current = false;
        setIsSOS(false);
      }
    };

    const onVoiceAnalysis = (payload = {}) => {
      setVoiceAnalysis(payload);
    };

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('agent-state-update', onAgentState);
    socket.on('voice-analysis', onVoiceAnalysis);

    if (!socket.connected) {
      socket.connect();
    }

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('agent-state-update', onAgentState);
      socket.off('voice-analysis', onVoiceAnalysis);
    };
  }, []);

  // --------------------------------------------------
  // GPS LOCATION TRACKING
  // --------------------------------------------------

  useEffect(() => {
    if (
      typeof navigator === 'undefined' ||
      !navigator.geolocation
    ) {
      setLocationStatus('unsupported');
      return undefined;
    }

    let mounted = true;

    const onSuccess = (position) => {
      if (!mounted) return;

      const next = {
        lat: position.coords.latitude,
        lng: position.coords.longitude,
        accuracy: position.coords.accuracy,
        timestamp: Date.now(),
        isApproximate: false,
      };

      const previous = lastLocationRef.current;

      // Ignore small GPS jitter when checking movement.
      if (
        !previous ||
        distanceMeters(previous, next) > 8
      ) {
        setLastMovedTime(Date.now());
      }

      lastLocationRef.current = next;
      updateLocation(next);
      setLocationStatus('live');

      if (socket.connected) {
        const currentUser = userRef.current || {};

        socket.emit('location-update', {
          ...next,
          userName: getUserName(currentUser),
          userPhone: getUserPhone(currentUser),
          isSOS: sosRef.current || alarmRef.current,
        });
      }
    };

    const onError = (error) => {
      if (!mounted) return;

      if (error.code === 1) {
        setLocationStatus('denied');
      } else {
        setLocationStatus('unavailable');
      }
    };

    navigator.geolocation.getCurrentPosition(
      onSuccess,
      onError,
      {
        enableHighAccuracy: true,
        timeout: 12000,
        maximumAge: 5000,
      }
    );

    const watchId = navigator.geolocation.watchPosition(
      onSuccess,
      onError,
      {
        enableHighAccuracy: true,
        maximumAge: 5000,
        timeout: 20000,
      }
    );

    return () => {
      mounted = false;
      navigator.geolocation.clearWatch(watchId);
    };
  }, [updateLocation]);

  // --------------------------------------------------
  // STOP VOICE GUARD AND RELEASE MICROPHONE
  // --------------------------------------------------

  const stopSarthiAudio = useCallback(() => {
    sarthiActiveRef.current = false;

    if (sarthiChunkTimerRef.current) {
      window.clearTimeout(sarthiChunkTimerRef.current);
    }

    sarthiChunkTimerRef.current = null;

    const recorder = sarthiRecorderRef.current;
    sarthiRecorderRef.current = null;

    if (recorder && recorder.state !== 'inactive') {
      try {
        recorder.stop();
      } catch {
        // Recorder may already have stopped.
      }
    }

    if (sarthiStreamRef.current) {
      sarthiStreamRef.current
        .getTracks()
        .forEach((track) => track.stop());
    }

    sarthiStreamRef.current = null;
    setSarthiMicStatus('off');
  }, []);

  // --------------------------------------------------
  // SEND AUDIO TO EXISTING FASTAPI TRANSCRIPTION API
  // --------------------------------------------------

  const sendSarthiAudioChunk = useCallback(
    async (blob) => {
      if (
        !blob ||
        blob.size < 500 ||
        sarthiUploadBusyRef.current ||
        !socket.connected ||
        !socket.id
      ) {
        return;
      }

      sarthiUploadBusyRef.current = true;

      try {
        const currentUser = userRef.current || {};
        const currentLocation = locationRef.current;

        const body = new FormData();

        body.append('audio', blob, 'sarthi-monitor.webm');
        body.append('audioMode', 'sarthi');
        body.append('socketId', socket.id);
        body.append('userName', getUserName(currentUser));
        body.append('userPhone', getUserPhone(currentUser));
        body.append('emergencyEmail', getUserEmergencyEmail(currentUser));
        body.append('emergencyPhone', getUserEmergencyPhone(currentUser));
        body.append('emergencyName', getUserEmergencyName(currentUser));
        body.append('lat', String(currentLocation.lat));
        body.append('lng', String(currentLocation.lng));

        const { data } = await api.post(
          '/api/transcribe',
          body,
          { timeout: 65000 }
        );

        if (data?.distress_detected) {
          setVoiceAnalysis({
            ...data,
            receivedAt: new Date().toISOString(),
            source: 'sarthi-live-audio',
          });
        }
      } catch (error) {
        // A failed audio upload must not stop GPS monitoring.
        console.warn(
          '[Sarthi] Live audio check failed:',
          getApiError(error, 'Transcription unavailable')
        );
      } finally {
        sarthiUploadBusyRef.current = false;
      }
    },
    []
  );

  // --------------------------------------------------
  // ENABLE OR DISABLE SARTHI SAFE WALK
  // --------------------------------------------------

  const toggleSarthiMode = useCallback(() => {
    if (isSarthiActive) {
      stopSarthiAudio();

      setIsSarthiActive(false);
      alarmRef.current = false;
      setIsSarthiAlarm(false);

      if (socket.connected) {
        socket.emit('stop-monitoring');
      }

      return;
    }

    setLastMovedTime(Date.now());
    setIsSarthiAlarm(false);
    alarmRef.current = false;
    setIsSarthiActive(true);
    sarthiActiveRef.current = true;

    if (socket.connected) {
      const currentUser = userRef.current || {};
      const currentLocation = locationRef.current;

      socket.emit('start-monitoring', {
        userName: getUserName(currentUser),
        userPhone: getUserPhone(currentUser),
        emergencyEmail: getUserEmergencyEmail(currentUser),
        emergencyPhone: getUserEmergencyPhone(currentUser),
        emergencyName: getUserEmergencyName(currentUser),
        location: {
          lat: currentLocation.lat,
          lng: currentLocation.lng,
        },
      });
    }

    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();

      window.speechSynthesis.speak(
        new SpeechSynthesisUtterance(
          'Sarthi safety monitoring enabled. ' +
            'Microphone monitoring is off until you enable Voice Guard.'
        )
      );
    }
  }, [isSarthiActive, stopSarthiAudio]);

  // --------------------------------------------------
  // OPTIONAL CONTINUOUS VOICE GUARD
  // --------------------------------------------------

  const toggleSarthiMic = useCallback(async () => {
    if (
      sarthiStreamRef.current ||
      sarthiMicStatus === 'listening'
    ) {
      stopSarthiAudio();
      return;
    }

    if (!isSarthiActive) {
      setAgentState((previous) => ({
        ...previous,
        message:
          'Enable Sarthi Safe Walk before enabling Voice Guard.',
      }));

      return;
    }

    sarthiActiveRef.current = true;

    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        !window.MediaRecorder
      ) {
        throw new Error(
          'This browser does not support microphone recording.'
        );
      }

      const stream =
        await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: false,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        });

      // The user might have disabled Sarthi while permission
      // was being requested.
      if (!sarthiActiveRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      sarthiStreamRef.current = stream;
      setSarthiMicStatus('listening');

      const recordClip = () => {
        if (
          !sarthiActiveRef.current ||
          !sarthiStreamRef.current
        ) {
          return;
        }

        let recorder;

        try {
          const mimeType = [
            'audio/webm;codecs=opus',
            'audio/webm',
          ].find((type) =>
            window.MediaRecorder.isTypeSupported?.(type)
          );

          recorder = mimeType
            ? new MediaRecorder(sarthiStreamRef.current, {
                mimeType,
              })
            : new MediaRecorder(sarthiStreamRef.current);
        } catch (error) {
          console.warn(
            '[Sarthi] Could not start audio recorder:',
            error
          );

          setSarthiMicStatus('error');
          return;
        }

        sarthiRecorderRef.current = recorder;
        const parts = [];

        recorder.ondataavailable = (event) => {
          if (event.data?.size) {
            parts.push(event.data);
          }
        };

        recorder.onstop = () => {
          if (sarthiRecorderRef.current === recorder) {
            sarthiRecorderRef.current = null;
          }

          const clip = new Blob(parts, {
            type: recorder.mimeType || 'audio/webm',
          });

          if (sarthiActiveRef.current) {
            void sendSarthiAudioChunk(clip);
          }

          if (sarthiActiveRef.current) {
            sarthiChunkTimerRef.current =
              window.setTimeout(recordClip, 250);
          }
        };

        recorder.start();

        sarthiChunkTimerRef.current = window.setTimeout(
          () => {
            if (recorder.state !== 'inactive') {
              recorder.stop();
            }
          },
          6000
        );
      };

      recordClip();
    } catch (error) {
      setSarthiMicStatus('blocked');

      setAgentState((previous) => ({
        ...previous,
        message:
          'Voice Guard microphone is unavailable. ' +
          'Check browser microphone permission.',
      }));

      console.warn(
        '[Sarthi] Microphone unavailable:',
        error
      );
    }
  }, [
    isSarthiActive,
    sarthiMicStatus,
    sendSarthiAudioChunk,
    stopSarthiAudio,
  ]);

  // Always release the microphone when the hook unmounts.
  useEffect(() => {
    return () => stopSarthiAudio();
  }, [stopSarthiAudio]);

  // --------------------------------------------------
  // MOVEMENT CHECK-IN ALARM
  // --------------------------------------------------

  const triggerSarthiAlarm = useCallback(
    (currentLoc = locationRef.current) => {
      if (alarmRef.current) return;

      alarmRef.current = true;
      setIsSarthiAlarm(true);

      if (socket.connected) {
        socket.emit('sarthi-mode-engaged', {
          location: currentLoc,
          userName: getUserName(userRef.current),
        });
      }

      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();

        window.speechSynthesis.speak(
          new SpeechSynthesisUtterance(
            'Sarthi movement check. ' +
              'If you are safe, confirm that you are okay.'
          )
        );
      }
    },
    []
  );

  // Check movement every five seconds.
  // Only run this check when actual GPS is available.
  useEffect(() => {
    if (
      !isSarthiActive ||
      isSarthiAlarm ||
      locationStatus !== 'live' ||
      location?.isApproximate
    ) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      if (Date.now() - lastMovedTime >= 15000) {
        triggerSarthiAlarm(locationRef.current);
      }
    }, 5000);

    return () => window.clearInterval(timer);
  }, [
    isSarthiActive,
    isSarthiAlarm,
    lastMovedTime,
    locationStatus,
    location?.isApproximate,
    triggerSarthiAlarm,
  ]);

  const cancelSarthiAlarm = useCallback(() => {
    alarmRef.current = false;
    setIsSarthiAlarm(false);
    setLastMovedTime(Date.now());

    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
  }, []);

  // --------------------------------------------------
  // SOS EMERGENCY WORKFLOW
  // --------------------------------------------------

  const triggerSOS = useCallback(
    (options = {}) => {
      const skipConfirm = options?.skipConfirm === true;
      const currentLocation = locationRef.current;

      const locationPrompt = currentLocation.isApproximate
        ? 'GPS is unavailable, so this may send only the ' +
          'approximate Nagpur map center. Continue with SOS anyway?'
        : 'Send an SOS with your current location to the ' +
          'connected emergency workflow? Only continue if you need help.';

      if (!skipConfirm && !window.confirm(locationPrompt)) {
        return;
      }

      if (userRef.current?.demo) {
        window.alert(
          'Demo mode does not send live emergency alerts. ' +
            'Sign in with your account to use the connected emergency workflow. ' +
            'If you are in immediate danger, call 112.'
        );

        return;
      }

      if (!socket.connected) {
        window.alert(
          'The safety server is not connected. ' +
            'Call 112 directly if you are in immediate danger.'
        );

        return;
      }

      alarmRef.current = false;
      setIsSarthiAlarm(false);

      sosRef.current = true;
      setIsSOS(true);

      const currentUser = userRef.current || {};

      socket.emit('location-update', {
        lat: currentLocation.lat,
        lng: currentLocation.lng,
        isSOS: true,
        userName: getUserName(currentUser),
        userPhone: getUserPhone(currentUser),
        emergencyEmail: getUserEmergencyEmail(currentUser),
        emergencyPhone: getUserEmergencyPhone(currentUser),
        emergencyName: getUserEmergencyName(currentUser),
        timestamp: Date.now(),
      });

      socket.emit('trigger-sos', {
        location: {
          lat: currentLocation.lat,
          lng: currentLocation.lng,
          isApproximate: Boolean(
            currentLocation.isApproximate
          ),
          accuracy: currentLocation.accuracy,
        },
        lat: currentLocation.lat,
        lng: currentLocation.lng,
        userName: getUserName(currentUser),
        userPhone: getUserPhone(currentUser),
        emergencyEmail: getUserEmergencyEmail(currentUser),
        emergencyPhone: getUserEmergencyPhone(currentUser),
        emergencyName: getUserEmergencyName(currentUser),
        severity: 'critical',
      });
    },
    []
  );

  // Confirm that the user is safe.
  const confirmSafe = useCallback(() => {
    if (socket.connected) {
      socket.emit('safety-confirmed');
    }

    sosRef.current = false;
    setIsSOS(false);
    cancelSarthiAlarm();
  }, [cancelSarthiAlarm]);

  const cancelIntercept = useCallback(() => {
    if (socket.connected) {
      socket.emit('intercept-cancel');
    }

    setAgentState((previous) => ({
      ...previous,
      message: 'Safety confirmation sent to the voice agent.',
    }));
  }, []);

  // --------------------------------------------------
  // PUBLIC HOOK API
  // Keep these names compatible with your dashboard.
  // --------------------------------------------------

  return {
    location,
    setLocation: updateLocation,
    locationStatus,

    socketConnected,

    isSarthiActive,
    toggleSarthiMode,

    toggleSarthiMic,
    sarthiMicStatus,

    isSarthiAlarm,
    cancelSarthiAlarm,
    triggerSarthiAlarm,

    isSOS,
    triggerSOS,

    agentState,
    voiceAnalysis,
    setVoiceAnalysis,

    confirmSafe,
    cancelIntercept,
  };
}

export default useTracker;
