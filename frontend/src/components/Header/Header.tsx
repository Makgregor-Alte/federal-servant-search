import { Link } from "react-router-dom";
import './Header.css'

export function Header() {
  return (
    <header className="site-header">
      <Link to="/" className="logo" aria-label="Pagina inicial">
        *LOGO* <strong>COMPANY</strong>
      </Link>
    </header>
  );
};