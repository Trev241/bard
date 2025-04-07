const socket = io();

socket.on("playing_track", () => window.location.reload());
