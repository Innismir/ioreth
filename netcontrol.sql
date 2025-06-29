CREATE TABLE netcontrol (
    checkin_id INTEGER PRIMARY KEY,
    callsign TEXT NOT NULL,
    net_name TEXT NOT NULL,
    date INT NOT NULL
);

CREATE TABLE debouncer (
    packet_id INTEGER PRIMARY KEY,
    callsign TEXT NOT NULL,
    message TEXT NOT NULL,
    datetime INT NOT NULL
);
