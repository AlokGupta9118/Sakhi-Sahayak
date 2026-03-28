require('dotenv').config();
const express = require('express');
const cors = require('cors');
const http = require('http');
const { Server } = require('socket.io');
const mongoose = require('mongoose');
const User = require('./models/User');

const app = express();
const server = http.createServer(app);

// Cross-Origin configuration
const io = new Server(server, {
  cors: { origin: '*', methods: ['GET', 'POST'] }
});

app.use(cors());
app.use(express.json());

let isMongoConnected = false;
const memoryUsers = []; // Fallback memory database

// MongoDB Connection
mongoose.connect(process.env.MONGO_URI, {
  serverSelectionTimeoutMS: 5000 // Fails fast in 5 seconds if IP blocked
}).then(() => {
  isMongoConnected = true;
  console.log('✅ Connected explicitly to MongoDB (Sakhi Cluster)');
}).catch(err => {
  console.log('⚠️ MongoDB Blocked (IP Whitelist Issue). Using Memory Database for Demo.');
});

// 1. Setup Backend Routes
const router = express.Router();

router.post('/signup', async (req, res) => {
  try {
    const { userName, userPhone, userPassword, emergencyName, emergencyPhone } = req.body;
    
    // --- FALLBACK MEMORY DB ---
    if (!isMongoConnected) {
      if (memoryUsers.find(u => u.phone === userPhone)) {
        return res.status(400).json({ success: false, msg: "User already exists! Please login." });
      }
      const newUser = { name: userName, phone: userPhone, password: userPassword, emergencyContact: { name: emergencyName, phone: emergencyPhone } };
      memoryUsers.push(newUser);
      return res.status(201).json({ success: true, user: newUser, msg: "Signup successful (Memory Mode)" });
    }

    // --- REAL MONGODB ---
    let existingUser = await User.findOne({ phone: userPhone });
    if (existingUser) {
      return res.status(400).json({ success: false, msg: "User with this phone number already exists! Please login." });
    }
    
    const newUser = new User({
      name: userName,
      phone: userPhone,
      password: userPassword,
      emergencyContact: {
        name: emergencyName,
        phone: emergencyPhone
      }
    });

    await newUser.save();
    return res.status(201).json({ success: true, user: newUser, msg: "Signup successful!" });
  } catch (err) {
    console.error("Signup Route Error: ", err);
    res.status(500).json({ success: false, error: err.message });
  }
});

router.post('/login', async (req, res) => {
  try {
    const { userPhone, userPassword } = req.body;
    
    // --- FALLBACK MEMORY DB ---
    if (!isMongoConnected) {
      const user = memoryUsers.find(u => u.phone === userPhone);
      if (!user) return res.status(404).json({ success: false, msg: "User not found! (Memory Mode)" });
      if (user.password !== userPassword) return res.status(401).json({ success: false, msg: "Invalid password!" });
      return res.status(200).json({ success: true, user: user, msg: "Login successful!" });
    }

    // --- REAL MONGODB ---
    const user = await User.findOne({ phone: userPhone });
    if (!user) {
      return res.status(404).json({ success: false, msg: "User not found!" });
    }
    
    if (user.password !== userPassword) {
      return res.status(401).json({ success: false, msg: "Invalid password!" });
    }
    
    return res.status(200).json({ success: true, user: user, msg: "Login successful!" });
  } catch (err) {
    console.error("Login Route Error: ", err);
    res.status(500).json({ success: false, error: err.message });
  }
});

const fs = require('fs');
const path = require('path');

router.get('/danger-zones', (req, res) => {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'safety_data.json'), 'utf8'));
    res.json(data.danger_zones || []);
  } catch (err) {
    res.json([]);
  }
});

router.get('/safety-data', (req, res) => {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'safety_data.json'), 'utf8'));
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: "Failed to load safety data" });
  }
});

router.get('/nearest', (req, res) => {
  try {
    const { lat, lng } = req.query;
    if (!lat || !lng) return res.status(400).json({ error: "Missing lat/lng" });
    
    const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'safety_data.json'), 'utf8'));
    const userLat = parseFloat(lat);
    const userLng = parseFloat(lng);

    const getDistance = (lat1, lon1, lat2, lon2) => {
      const p1 = parseFloat(lat1), o1 = parseFloat(lon1), p2 = parseFloat(lat2), o2 = parseFloat(lon2);
      if (isNaN(p1) || isNaN(o1) || isNaN(p2) || isNaN(o2)) return 99999;

      const R = 6371; // km
      const dLat = (p2 - p1) * Math.PI / 180;
      const dLon = (o2 - o1) * Math.PI / 180;
      const a = 
        Math.sin(dLat/2) * Math.sin(dLat/2) +
        Math.cos(p1 * Math.PI / 180) * Math.cos(p2 * Math.PI / 180) * 
        Math.sin(dLon/2) * Math.sin(dLon/2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      return R * c;
    };

    const findNearest = (list) => {
      if (!list || list.length === 0) return null;
      let nearest = null;
      let minDistance = Infinity;

      list.forEach(item => {
        const itemLat = item.lat !== undefined ? item.lat : (item.center ? item.center[0] : null);
        const itemLng = item.lng !== undefined ? item.lng : (item.center ? item.center[1] : null);
        
        if (itemLat !== null && itemLng !== null) {
          const d = getDistance(userLat, userLng, itemLat, itemLng);
          if (d < minDistance) {
            minDistance = d;
            nearest = { ...item, distance: d };
          }
        }
      });
      return nearest;
    };

    res.json({
      police_station: findNearest(data.police_stations),
      hospital: findNearest(data.hospitals),
      metro: findNearest(data.metro_stations),
      danger_zone: findNearest(data.danger_zones)
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.use('/api', router);

// 2. Setup Real-time WebSockets
const liveTrackingData = {};

io.on('connection', (socket) => {
  console.log(`[BACKEND] Connected Client: ${socket.id}`);

  // Broadcast continuous GPS across socket channels
  socket.on('location-update', (data) => {
    liveTrackingData[socket.id] = data;
    // Broadcast back for Family Dashboard to consume!
    io.emit('family-dashboard-sync', liveTrackingData);
  });

  socket.on('trigger-sos', (data) => {
    console.log('\n===========================================');
    console.log('🚨 EMERGENCY SOS DETECTED 🚨');
    console.log('Fetching Mic Access and Contact Notifiers...');
    console.log('===========================================\n');
    io.emit('emergency-broadcast-sent', { source: socket.id, loc: data });
  });

  socket.on('sarthi-mode-engaged', (data) => {
    console.log(`\n[BACKEND] Sarthi Mode engaged on socket ${socket.id} (Stopped for 30s).`);
  });

  socket.on('disconnect', () => {
    delete liveTrackingData[socket.id];
    io.emit('family-dashboard-sync', liveTrackingData);
    console.log(`[BACKEND] Disconnected Client: ${socket.id}`);
  });
});

// Run server
const PORT = 5001;
server.listen(PORT, () => {
  console.log(`[BACKEND STARTED] Full node.js architecture running perfectly on Port ${PORT}`);
});
