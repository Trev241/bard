const socket = io();

const log = (data) => {
  const logContainer = document.getElementById("logContainer");
  const messageElement = document.createElement("p");
  messageElement.textContent = data.message;
  logContainer.appendChild(messageElement);
  // messageElement.scrollIntoView();
  logContainer.scrollTop = logContainer.scrollHeight;
};

const updatePlaylist = (data) => {
  const ulElement = document.getElementById("nextUp");
  ulElement.innerHTML = "";
  for (const track of data.queue.slice(1, 4)) {
    ulElement.innerHTML += `
      <li class="mb-2">
        <div class="h-24 flex items-center">
          <img
            class="h-24 rounded-xl"
            src="${track.thumbnail}"
          />
          <div class="px-4 text-start line-clamp-2">
            <h3 class="text-md font-semibold">${track.title}</h3>
          </div>
        </div>
      </li>
    `;
  }

  if (data.queue.length === 1) {
    ulElement.innerHTML = `
      <p>Wow, looks like nothing else is queued.</p>
    `;
  } else if (data.queue.length > 4) {
    ulElement.innerHTML += `
      <li class="mb-4">
        <p class="italic">
          and ${data.queue.length - 4} more.
        </p>
      </li>
    `;
  }
};

const updatePlayingNow = (data) => {
  const imgElement = document.getElementById("nowPlayingImg");
  const ttlElement = document.getElementById("nowPlayingTtl");
  const spnElement = document.getElementById("requestedBy");

  imgElement.setAttribute("src", data.thumbnail);
  ttlElement.setAttribute("href", data.webpage_url);
  ttlElement.textContent = data.title;
  spnElement.innerHTML = `Playing on ${data.requester}'s request`;

  updatePlaylist(data);
};

const updateCallMembers = (data) => {
  console.log("Message received");

  const ulElement = document.getElementById("callMemberList");
  ulElement.innerHTML = "";
  for (const member of data.members.slice(0, 3)) {
    ulElement.innerHTML += `
      <li class="flex items-center mb-2">
        <img class="rounded-full w-12" src="${member.avatar}" />
        <h3 class="ms-4">${member.display_name}</h3>
      </li>
    `;
  }

  if (data.members.length == 0) {
    ulElement.innerHTML = `
      <p>No one on call!</p>
    `;
  } else if (data.members.length > 3) {
    ulElement.innerHTML += `
      <li class="italic">
        and ${data.members.length - 3} more.
      </li>
    `;
  }
};

socket.on("stdout_message", log);
socket.on("stderr_message", log);
socket.on("playing_track", updatePlayingNow);
socket.on("playlist_update", updatePlaylist);
socket.on("call_list_update", updateCallMembers);
