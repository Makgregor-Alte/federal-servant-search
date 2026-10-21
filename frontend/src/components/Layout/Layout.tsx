import { Outlet } from "react-router-dom";

import { Header } from "../Header/Header";
import './Layout.css'

export function Layout() {
  return (
    <div className="layout">
      <Header />
      <Outlet />
    </div>
  );
}