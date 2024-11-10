const socket = io();

const log = (data) => {
  const logContainer = document.getElementById("logContainer");
  const messageElement = document.createElement("li");
  messageElement.textContent = data.message;
  logContainer.appendChild(messageElement);
  messageElement.scrollIntoView();
};

socket.on("stdout_message", log);
socket.on("stderr_message", log);
