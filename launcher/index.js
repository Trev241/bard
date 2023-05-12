const express = require("express");
const cors = require("cors");
const path = require("path");

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

app.use(require("./routes"));

const PORT = 5000;
app.listen(PORT, () => console.log(`Launcher listening on port ${PORT}`));
