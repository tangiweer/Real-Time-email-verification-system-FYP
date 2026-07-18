export default function TopNav() {
  return (
    <header className="top-nav">
      <div className="user-profile" style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <div className="name" style={{ fontWeight: 600, fontSize: '0.95rem' }}>Admin User</div>
      </div>
    </header>
  );
}
