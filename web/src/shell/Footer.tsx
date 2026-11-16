import { Trans, useTranslation } from 'react-i18next';

const ext = { target: '_blank', rel: 'noopener noreferrer' } as const;

/** Upstream credits and the AGPL notice (kept from the 1.x footer). */
export function Footer({ version }: { version: string }) {
  useTranslation();
  const year = new Date().getFullYear();
  return (
    <footer className="footer">
      <p>
        <Trans
          i18nKey="footer.main"
          values={{ year, version }}
          components={{ src: <a href="https://github.com/drlight17/mta-log-parser" {...ext} />, lic: <a href="https://www.gnu.org/licenses/agpl-3.0.html" {...ext} /> }}
        />
      </p>
      <p className="footer-upstream">
        <Trans
          i18nKey="footer.privex"
          components={{ src: <a href="https://github.com/Privex/postfix-parser" {...ext} />, lic: <a href="https://www.gnu.org/licenses/agpl-3.0.html" {...ext} /> }}
        />
      </p>
    </footer>
  );
}
