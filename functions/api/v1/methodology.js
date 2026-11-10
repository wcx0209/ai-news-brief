import { json, METHODOLOGY, options } from "../../_lib/public-data.js";

export async function onRequestOptions() { return options(); }
export async function onRequestGet() { return json({ object: "methodology", ...METHODOLOGY }); }
