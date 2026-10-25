import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import QueuePage from "./QueuePage";
import FormPage from "./FormPage";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/" element={<QueuePage />} />
        <Route path="/forms/:id" element={<FormPage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
