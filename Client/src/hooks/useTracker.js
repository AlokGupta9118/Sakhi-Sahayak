import { useState, useEffect, useRef } from 'react';
import { io } from 'socket.io-client';

const socket = io('http://localhost:5001');

// Haversine formula to calculate distance in meters
function getDistance(lat1, lon1, lat2, lon2) {
  const R = 6371e3; // metres
  const φ1 = lat1 * Math.PI/180;
  const φ2 = lat2 * Math.PI/180;
  const Δφ = (lat2-lat1) * Math.PI/180;
  const Δλ = (lon2-lon1) * Math.PI/180;

  const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
          Math.cos(φ1) * Math.cos(φ2) *
          Math.sin(Δλ/2) * Math.sin(Δλ/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

  return R * c;
}

export function useTracker() {
  const [location, setLocation] = useState({ lat: 28.6139, lng: 77.2090 });
  const [isSarthiActive, setIsSarthiActive] = useState(false); // Manually turned on by user
  const [isSarthiAlarm, setIsSarthiAlarm] = useState(false); // Tripped by no movement
  const [isSOS, setIsSOS] = useState(false);
  
  const [lastMovedTime, setLastMovedTime] = useState(Date.now());
  const historyRef = useRef([]);

  // Active Time Poller: Checks unconditionally if 30s have passed since last known movement
  useEffect(() => {
    let interval;
    if (isSarthiActive && !isSarthiAlarm) {
      interval = setInterval(() => {
        if (Date.now() - lastMovedTime >= 30000) {
          triggerSarthiAlarm(location);
        }
      }, 5000); // Polls every 5 seconds
    }
    return () => clearInterval(interval);
  }, [isSarthiActive, isSarthiAlarm, lastMovedTime, location]);

  useEffect(() => {
    if (!("geolocation" in navigator)) return;
    
    // Initial request
    navigator.geolocation.getCurrentPosition(
      (pos) => setLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      (err) => console.log(err),
      { enableHighAccuracy: true }
    );

    const watchId = navigator.geolocation.watchPosition((pos) => {
      const newLoc = { lat: pos.coords.latitude, lng: pos.coords.longitude, time: Date.now() };
      setLocation(newLoc);
      
      socket.emit('location-update', newLoc);
      
      const history = historyRef.current;
      const lastKnown = history.length > 0 ? history[history.length - 1] : null;

      if (lastKnown) {
        // If they genuinely traveled more than 5 meters since the very last ping, reset their timer!
        const dist = getDistance(lastKnown.lat, lastKnown.lng, newLoc.lat, newLoc.lng);
        if (dist > 5) {
          setLastMovedTime(Date.now());
        }
      } else {
        setLastMovedTime(Date.now()); // First lock
      }

      history.push(newLoc);
      
      // Keep only 35s of history to prevent memory leak
      const now = Date.now();
      while (history.length > 0 && now - history[0].time > 35000) {
        history.shift();
      }
      
    }, (err) => console.log(err), { enableHighAccuracy: true });

    return () => navigator.geolocation.clearWatch(watchId);
  }, []);

  const toggleSarthiMode = () => {
    const nextState = !isSarthiActive;
    setIsSarthiActive(nextState);
    if (!nextState) {
      setIsSarthiAlarm(false); // turn off alarm if user turns off Sarthi mode completely
    } else {
      setLastMovedTime(Date.now()); // Reset the 30s timer fresh from this exact moment
      // Announce activated via voice briefly
      if ('speechSynthesis' in window) {
        const msg = new SpeechSynthesisUtterance("Sarthi Mode has been activated. Monitoring movement.");
        msg.rate = 1.1;
        window.speechSynthesis.speak(msg);
      }
    }
  };

  const triggerSarthiAlarm = (currentLoc) => {
    setIsSarthiAlarm(true);
    socket.emit('sarthi-mode-engaged', currentLoc || location);
    
    // Play an audible voice message immediately
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance("Warning. Sarthi Mode parameter tripped. You have been stationary for too long. Opening microphone and alerting your emergency contacts immediately.");
      utterance.pitch = 1.2;
      utterance.rate = 0.9;
      utterance.volume = 1;
      window.speechSynthesis.speak(utterance);
    }
    
    // Request Microphone access
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then((stream) => {
        console.log("Audio Stream active for Sarthi Alarm", stream);
      })
      .catch((err) => {
        console.error("Microphone denied", err);
      });
  };

  const triggerSOS = () => {
    setIsSOS(true);
    socket.emit('trigger-sos', location);
    
    if ('speechSynthesis' in window) {
       window.speechSynthesis.speak(new SpeechSynthesisUtterance("SOS Initiated. Dispatching location to authorities and contacts."));
    }
    
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => console.log("SOS Mic Active", stream));
  };

  const cancelSarthiAlarm = () => {
    setIsSarthiAlarm(false);
    setLastMovedTime(Date.now()); // Restart the 30s clock
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel(); // Shut off the alarming voice instantly
    }
  };

  return { location, isSarthiActive, toggleSarthiMode, isSarthiAlarm, cancelSarthiAlarm, triggerSarthiAlarm, isSOS, triggerSOS, setLocation };
}
