import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, CalendarDays, Check, ChevronRight, ClipboardList, Home, ImageIcon, MapPin, MoreHorizontal, Phone, Users, Wrench, X } from 'lucide-react';
import './index.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';

const STATUS_LABELS = {
  NUOVA: 'Nuova',
  ACCETTATA: 'Accettata',
  PROGRAMMATA: 'Programmato',
  IN_CORSO: 'In corso',
  COMPLETATA: 'Completata',
  RIFIUTATA: 'Rifiutata',
};

const URGENCY_LABELS = {
  alta: 'Alta',
  media: 'Media',
  bassa: 'Bassa',
};

function App() {
  const [page, setPage] = useState('dashboard');
  const [token, setToken] = useState(localStorage.getItem('access_token') || '');
  const [email, setEmail] = useState('dev@example.com');
  const [password, setPassword] = useState('secret123');
  const [requests, setRequests] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [users, setUsers] = useState([]);
  const [appointments, setAppointments] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [customerHistory, setCustomerHistory] = useState(null);
  const [conversation, setConversation] = useState(null);
  const [replyBody, setReplyBody] = useState('');
  const [assigneeId, setAssigneeId] = useState('');
  const [attachments, setAttachments] = useState([]);
  const [filters, setFilters] = useState({ status: 'all', search: '' });
  const [currentUser, setCurrentUser] = useState(null);

  useEffect(() => {
    if (token) {
      Promise.all([fetchMe(), fetchDashboard(), fetchRequests(), fetchCustomers(), fetchUsers(), fetchAppointments()]);
    } else {
      setPage('login');
    }
  }, [token]);

  const filteredRequests = useMemo(() => {
    return requests.filter((item) => {
      const matchesStatus = filters.status === 'all' || item.status === filters.status;
      const haystack = `${item.category || ''} ${item.city || ''} ${item.description || ''} ${customerName(item.customer)}`.toLowerCase();
      const matchesSearch = !filters.search || haystack.includes(filters.search.toLowerCase());
      return matchesStatus && matchesSearch;
    });
  }, [filters, requests]);

  const recentRequests = useMemo(
    () => [...requests]
      .sort((first, second) => new Date(second.created_at || 0) - new Date(first.created_at || 0))
      .slice(0, 4),
    [requests],
  );

  function customerName(customer) {
    if (!customer) return 'Cliente non associato';
    return [customer.first_name, customer.last_name].filter(Boolean).join(' ') || customer.phone || 'Cliente';
  }

  function customerInitials(customer) {
    return customerName(customer)
      .split(' ')
      .filter(Boolean)
      .map((part) => part[0])
      .join('')
      .slice(0, 2)
      .toUpperCase();
  }

  function formatDate(value) {
    if (!value) return 'N/D';
    return new Date(value).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' });
  }

  function attachmentHref(fileUrl) {
    if (!fileUrl) return '#';
    if (fileUrl.startsWith('http://') || fileUrl.startsWith('https://')) {
      return fileUrl;
    }
    return `${API_URL.replace('/api', '')}${fileUrl}`;
  }

  function requestSummary(item) {
    return STATUS_LABELS[item.status] || item.status || 'In lavorazione';
  }

  async function fetchMe() {
    try {
      const res = await fetch(`${API_URL}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        setCurrentUser(null);
        return;
      }
      const data = await res.json();
      setCurrentUser(data);
    } catch (err) {
      setCurrentUser(null);
    }
  }

  async function fetchDashboard() {
    const res = await fetch(`${API_URL}/dashboard/summary`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error('Impossibile caricare la dashboard');
    setDashboard(await res.json());
  }

  async function doLogin(e) {
    e.preventDefault();
    setError('');
    try {
      setLoading(true);
      const res = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) throw new Error('Login fallito');
      const body = await res.json();
      setToken(body.access_token);
      localStorage.setItem('access_token', body.access_token);
      if (body.refresh_token) localStorage.setItem('refresh_token', body.refresh_token);
      setPage('dashboard');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function fetchRequests() {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/requests`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Impossibile caricare le richieste');
      const data = await res.json();
      setRequests(data);
      if (!selected && data.length > 0) {
        setSelected(data[0]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function fetchCustomers() {
    const res = await fetch(`${API_URL}/customers`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error('Impossibile caricare i clienti');
    setCustomers(await res.json());
  }

  async function fetchUsers() {
    const res = await fetch(`${API_URL}/users`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error('Impossibile caricare gli utenti');
    setUsers(await res.json());
  }

  async function fetchAppointments() {
    const res = await fetch(`${API_URL}/appointments`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error('Impossibile caricare il calendario');
    setAppointments(await res.json());
  }

  async function openRequest(requestItem) {
    setSelected(requestItem);
    setAssigneeId(requestItem?.assigned_user_id ? String(requestItem.assigned_user_id) : '');
    setPage('request-detail');
    setAttachments([]);
    if (requestItem?.customer_id) {
      await openCustomer(requestItem.customer_id);
    } else {
      setSelectedCustomer(null);
      setCustomerHistory(null);
    }
    const res = await fetch(`${API_URL}/requests/${requestItem.id}/attachments`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      setAttachments(await res.json());
    }
  }

  async function openCustomer(customerId) {
    const [customerRes, historyRes, conversationRes] = await Promise.all([
      fetch(`${API_URL}/customers/${customerId}`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/customers/${customerId}/history`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/customers/${customerId}/conversation`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    if (customerRes.ok) {
      setSelectedCustomer(await customerRes.json());
    }
    if (historyRes.ok) {
      setCustomerHistory(await historyRes.json());
    }
    if (conversationRes.ok) {
      setConversation(await conversationRes.json());
    } else {
      setConversation(null);
    }
  }

  async function sendReply() {
    if (!selectedCustomer || !replyBody.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/customers/${selectedCustomer.id}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ body: replyBody.trim() }),
      });
      if (!res.ok) {
        const payload = await res.json();
        throw new Error(payload.detail || 'Invio messaggio non riuscito');
      }
      setReplyBody('');
      await openCustomer(selectedCustomer.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function uploadAttachment(event) {
    const file = event.target.files?.[0];
    if (!file || !selected) return;
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_URL}/requests/${selected.id}/attachments`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    if (!res.ok) {
      setError('Upload allegato non riuscito');
      return;
    }
    await openRequest(selected);
  }

  async function acceptRequest(id) {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/requests/${id}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ assigned_user_id: null }),
      });
      if (!res.ok) {
        const b = await res.json();
        throw new Error(b.detail || 'Errore accettazione');
      }
      const updatedRequest = await res.json();
      if (selected?.id === id) setSelected(updatedRequest);
      await Promise.all([fetchRequests(), fetchDashboard(), fetchAppointments()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function rejectRequest(id) {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/requests/${id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const b = await res.json();
        throw new Error(b.detail || 'Errore rifiuto');
      }
      const updatedRequest = await res.json();
      if (selected?.id === id) setSelected(updatedRequest);
      await Promise.all([fetchRequests(), fetchDashboard()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function completeRequest(id) {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/requests/${id}/complete`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const b = await res.json();
        throw new Error(b.detail || 'Errore completamento');
      }
      await Promise.all([fetchRequests(), fetchDashboard(), fetchAppointments()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function assignRequest(id) {
    if (!assigneeId) {
      setError('Seleziona prima un tecnico da assegnare');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/requests/${id}/assign?assigned_user_id=${encodeURIComponent(assigneeId)}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const b = await res.json();
        throw new Error(b.detail || 'Errore assegnazione');
      }
      const updated = await res.json();
      setSelected(updated);
      await Promise.all([fetchRequests(), fetchDashboard(), fetchAppointments()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function userLabel(user) {
    return [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email;
  }

  function logout() {
    setToken('');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setRequests([]);
    setPage('login');
    setCurrentUser(null);
  }

  return (
    <div className={`app-shell ${page === 'dashboard' ? 'dashboard-shell' : ''}`}>
      <header className="topbar">
        <div>
          <p className="eyebrow">ArtigianAI</p>
          <h1>{page === 'dashboard' && currentUser ? `Ciao ${currentUser.first_name}` : page === 'request-detail' ? 'Dettaglio richiesta' : page === 'customers' ? 'Clienti' : page === 'settings' ? 'Profilo' : page === 'requests' ? 'Richieste' : 'ArtigianAI'}</h1>
          {currentUser && page === 'dashboard' && <p className="subcopy">Ecco il riepilogo di oggi.</p>}
        </div>
        {token && page === 'request-detail' && <button className="icon-button" aria-label="Torna alle richieste" onClick={() => setPage('requests')}><ArrowLeft size={20} /></button>}
      </header>

      <main>
        {page === 'login' && (
          <section className="form-panel">
            <h2>Login</h2>
            <form onSubmit={doLogin}>
              <label>
                Email
                <input value={email} onChange={(e) => setEmail(e.target.value)} required />
              </label>
              <label>
                Password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </label>
              <button type="submit">Accedi</button>
            </form>
            {loading && <p>Caricamento...</p>}
            {error && <p className="error">{error}</p>}
          </section>
        )}

        {token && page === 'dashboard' && (
          <>
            <section className="dashboard-grid">
              <article className="metric-card metric-highlight">
                <span>Nuove richieste</span>
                <strong>{dashboard?.new_requests ?? 0}</strong>
              </article>
              <article className="metric-card metric-highlight">
                <span>Interventi</span>
                <strong>{appointments.length}</strong>
              </article>
              <article className="metric-card">
                <span>In corso</span>
                <strong>{dashboard?.accepted_requests ?? 0}</strong>
              </article>
              <article className="metric-card">
                <span>Completati</span>
                <strong>{dashboard?.completed_requests ?? 0}</strong>
              </article>
            </section>
            <section className="list-panel">
              <div className="section-heading">
                <div>
                  <h2>Richieste recenti</h2>
                  <p>Le ultime richieste ricevute dai clienti.</p>
                </div>
                <button className="text-action" onClick={() => setPage('requests')}>Vedi tutte</button>
              </div>
              <div className="request-list">
                {recentRequests.length === 0 ? (
                  <p>Nessuna richiesta ricevuta.</p>
                ) : recentRequests.map((requestItem) => (
                  <article key={requestItem.id} className="request-card dashboard-request-card" onClick={() => openRequest(requestItem)}>
                    <span className={`urgency-dot urgency-${requestItem.urgency || 'media'}`} aria-hidden="true" />
                    <div className="request-card-content">
                      <div className="card-topline">
                        <h3>{customerName(requestItem.customer)}</h3>
                        <span className="muted">{formatDate(requestItem.created_at)}</span>
                      </div>
                      <p>{requestItem.description || requestItem.category || 'Richiesta senza descrizione'}</p>
                      <span className="request-location"><MapPin size={15} /> {requestItem.city || requestItem.address || 'Luogo da confermare'}</span>
                    </div>
                    <ChevronRight className="request-chevron" size={20} aria-hidden="true" />
                  </article>
                ))}
              </div>
            </section>
          </>
        )}

        {token && page === 'requests' && (
            <section className="list-panel">
              <div className="section-heading">
                <div>
                  <h2>Richieste</h2>
                  <p>Gestisci nuove richieste da WhatsApp, telefono e web in un'unica coda.</p>
                </div>
                <button onClick={fetchRequests}>Aggiorna</button>
              </div>
              <div className="filters-row">
                <input
                  placeholder="Cerca cliente, categoria o città"
                  value={filters.search}
                  onChange={(e) => setFilters((prev) => ({ ...prev, search: e.target.value }))}
                />
                <select value={filters.status} onChange={(e) => setFilters((prev) => ({ ...prev, status: e.target.value }))}>
                  <option value="all">Tutti gli stati</option>
                  <option value="NUOVA">Nuove</option>
                  <option value="ACCETTATA">Accettate</option>
                  <option value="COMPLETATA">Completate</option>
                  <option value="RIFIUTATA">Rifiutate</option>
                </select>
              </div>
              <div className="request-tabs" aria-label="Filtra richieste per stato">
                <button className={filters.status === 'all' ? 'tab-active' : ''} onClick={() => setFilters((prev) => ({ ...prev, status: 'all' }))}>Tutte</button>
                <button className={filters.status === 'NUOVA' ? 'tab-active' : ''} onClick={() => setFilters((prev) => ({ ...prev, status: 'NUOVA' }))}>Nuove</button>
                <button className={filters.status === 'ACCETTATA' ? 'tab-active' : ''} onClick={() => setFilters((prev) => ({ ...prev, status: 'ACCETTATA' }))}>Accettate</button>
                <button className={filters.status === 'COMPLETATA' ? 'tab-active' : ''} onClick={() => setFilters((prev) => ({ ...prev, status: 'COMPLETATA' }))}>Completate</button>
              </div>
              {loading ? (
                <p>Caricamento...</p>
              ) : error ? (
                <p className="error">{error}</p>
              ) : filteredRequests.length === 0 ? (
                <p>Nessuna richiesta trovata.</p>
              ) : (
                <div className="request-list">
                  {filteredRequests.map((r) => (
                    <article key={r.id} className={`request-card ${selected?.id === r.id ? 'selected-card' : ''}`}>
                      <div className="card-topline">
                        <span className="status-badge">{requestSummary(r)}</span>
                        <span className="muted">{formatDate(r.created_at)}</span>
                      </div>
                      <h3>{r.category || 'Nuova richiesta'} • {r.city || 'Città da confermare'}</h3>
                      <p>{customerName(r.customer)}</p>
                      <p>{r.description}</p>
                      <div className="card-meta">
                        <span>{r.source || 'manuale'}</span>
                        <span>{URGENCY_LABELS[r.urgency] || r.urgency || 'Media'}</span>
                      </div>
                      <div className="actions">
                        <button className="secondary-action" onClick={() => openRequest(r)}>Dettaglio <ChevronRight size={17} /></button>
                        <button className="accept-action" aria-label="Accetta richiesta" onClick={() => acceptRequest(r.id)}><Check size={18} /> Accetta</button>
                        <button className="reject-action" aria-label="Rifiuta richiesta" onClick={() => rejectRequest(r.id)}><X size={18} /> Rifiuta</button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}

          {token && page === 'request-detail' && (
            <section className="detail-panel">
              {!selected ? (
                <p>Seleziona una richiesta per vedere i dettagli.</p>
              ) : (
                <>
                  <div className="section-heading">
                    <div>
                      <span className="source-line">Ricevuta da {selected.source === 'whatsapp' ? 'WhatsApp' : selected.source || 'cliente'}</span>
                      <h2>{requestSummary(selected)}</h2>
                    </div>
                    <span className={`status-badge detail-status status-${(selected.status || '').toLowerCase()}`}>{requestSummary(selected)}</span>
                  </div>

                  <article className="customer-summary">
                    <span className="customer-avatar">{customerInitials(selectedCustomer || selected.customer)}</span>
                    <div>
                      <h3>{customerName(selectedCustomer || selected.customer)}</h3>
                      <p>{selectedCustomer?.phone || 'Telefono non disponibile'}</p>
                    </div>
                    {selectedCustomer?.phone && <a className="phone-button" href={`tel:${selectedCustomer.phone.replace(/\s/g, '')}`} aria-label={`Chiama ${customerName(selectedCustomer)}`}><Phone size={19} /></a>}
                  </article>

                  <section className="request-facts">
                    <div className="fact-row">
                      <MapPin size={18} />
                      <div><span>Indirizzo</span><strong>{selectedCustomer?.address || selected.address || 'Indirizzo da confermare'}{selected.city ? `, ${selected.city}` : ''}</strong></div>
                    </div>
                    <div className="fact-row">
                      <Wrench size={18} />
                      <div><span>Problema</span><strong>{selected.description || selected.category || 'Descrizione assente'}</strong></div>
                    </div>
                    <div className={`fact-row urgency-row urgency-${selected.urgency || 'media'}`}>
                      <span className="urgency-dot" aria-hidden="true" />
                      <div><span>Urgenza</span><strong>{URGENCY_LABELS[selected.urgency] || selected.urgency || 'Media'}</strong></div>
                    </div>
                  </section>

                  <article className="detail-card">
                    <div className="section-heading">
                      <div>
                        <h3>Assegna intervento</h3>
                        <p>Seleziona il tecnico che gestira la richiesta e invia subito un aggiornamento WhatsApp al cliente.</p>
                      </div>
                    </div>
                    <div className="assignment-row">
                      <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
                        <option value="">Seleziona un tecnico</option>
                        {users.map((user) => (
                          <option key={user.id} value={user.id}>{userLabel(user)} • {user.role}</option>
                        ))}
                      </select>
                      <button onClick={() => assignRequest(selected.id)}>Assegna</button>
                    </div>
                  </article>

                  <article className="detail-card">
                    <div className="section-heading">
                      <div>
                        <h3>Foto WhatsApp</h3>
                        <p>{attachments.length ? `${attachments.length} foto ricevute dal cliente` : 'Nessuna foto ricevuta.'}</p>
                      </div>
                      <label className="upload-button">
                        Carica allegato
                        <input type="file" onChange={uploadAttachment} hidden />
                      </label>
                    </div>
                    <div className="attachment-grid">
                      {attachments.length === 0 ? (
                        <div className="empty-photo"><ImageIcon size={24} /><span>In attesa di una foto</span></div>
                      ) : attachments.map((item) => (
                        <a key={item.id} className="attachment-card" href={attachmentHref(item.file_url)} target="_blank" rel="noreferrer">
                          {item.file_type?.startsWith('image/') ? <img src={attachmentHref(item.file_url)} alt={item.caption || 'Foto inviata dal cliente'} /> : <><ImageIcon size={24} /><strong>{item.caption || item.file_type || 'Allegato'}</strong></>}
                        </a>
                      ))}
                    </div>
                  </article>

                  <div className="request-action-bar">
                    <button className="accept-action" onClick={() => acceptRequest(selected.id)}><Check size={18} /> Accetta</button>
                    {selectedCustomer?.phone ? <a className="call-action" href={`tel:${selectedCustomer.phone.replace(/\s/g, '')}`}><Phone size={18} /> Chiama</a> : <button className="call-action" disabled><Phone size={18} /> Chiama</button>}
                    <button className="reject-action" onClick={() => rejectRequest(selected.id)}><X size={18} /> Rifiuta</button>
                  </div>

                  <article className="detail-card">
                    <h3>Storico cliente</h3>
                    {customerHistory?.service_requests?.length ? (
                      <div className="history-list">
                        {customerHistory.service_requests.slice(0, 5).map((item) => (
                          <div key={item.id} className="history-row">
                            <strong>{item.category || 'Intervento'}</strong>
                            <span>{requestSummary(item)} • {formatDate(item.created_at)}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p>Nessuno storico disponibile.</p>
                    )}
                  </article>

                  <article className="detail-card">
                    <div className="section-heading">
                      <div>
                        <h3>Conversazione WhatsApp</h3>
                        <p>Replica direttamente al lead senza uscire dal pannello operativo.</p>
                      </div>
                    </div>
                    {conversation?.messages?.length ? (
                      <div className="message-thread">
                        {conversation.messages.map((message) => (
                          <div key={message.id} className={`message-bubble ${message.sender_type === 'business' ? 'message-outbound' : 'message-inbound'}`}>
                            <strong>{message.sender_type === 'business' ? 'Operatore' : 'Cliente'}</strong>
                            <p>{message.content || 'Messaggio vuoto'}</p>
                            <span>{formatDate(message.created_at)}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p>Nessuna conversazione WhatsApp disponibile per questo cliente.</p>
                    )}
                    {selectedCustomer?.phone && (
                      <div className="reply-box">
                        <textarea
                          value={replyBody}
                          onChange={(e) => setReplyBody(e.target.value)}
                          placeholder="Scrivi una risposta WhatsApp per il cliente"
                        />
                        <button onClick={sendReply}>Invia risposta</button>
                      </div>
                    )}
                  </article>
                </>
              )}
            </section>
        )}

        {token && page === 'customers' && (
          <>
            <section className="list-panel">
              <div className="section-heading">
                <div>
                  <h2>Clienti</h2>
                  <p>Rubrica clienti con storico richieste e messaggi.</p>
                </div>
              </div>
              <div className="request-list">
                {customers.map((customer) => (
                  <article key={customer.id} className={`request-card ${selectedCustomer?.id === customer.id ? 'selected-card' : ''}`}>
                    <h3>{customerName(customer)}</h3>
                    <p>{customer.phone || 'Telefono non disponibile'}</p>
                    <p>{customer.city || 'Città non disponibile'}</p>
                    <div className="actions">
                      <button onClick={() => { openCustomer(customer.id); setPage('customers'); }}>Apri</button>
                    </div>
                  </article>
                ))}
              </div>
            </section>
            <section className="detail-panel">
              {!selectedCustomer ? (
                <p>Seleziona un cliente per vederne il profilo.</p>
              ) : (
                <>
                  <h2>{customerName(selectedCustomer)}</h2>
                  <p>{selectedCustomer.phone || 'Telefono non disponibile'}</p>
                  <p>{selectedCustomer.email || 'Email non disponibile'}</p>
                  <p>{selectedCustomer.address || 'Indirizzo non disponibile'}</p>
                  <article className="detail-card">
                    <h3>Richieste recenti</h3>
                    {customerHistory?.service_requests?.map((item) => (
                      <div key={item.id} className="history-row">
                        <strong>{item.category || 'Intervento'}</strong>
                        <span>{requestSummary(item)} • {formatDate(item.created_at)}</span>
                      </div>
                    )) || <p>Nessuna richiesta.</p>}
                  </article>
                  <article className="detail-card">
                    <h3>Messaggi</h3>
                    {customerHistory?.messages?.map((item) => (
                      <div key={item.id} className="history-row">
                        <strong>{item.sender_type}</strong>
                        <span>{item.content || 'Messaggio vuoto'} • {formatDate(item.created_at)}</span>
                      </div>
                    )) || <p>Nessun messaggio disponibile.</p>}
                  </article>
                  <article className="detail-card">
                    <h3>Rispondi su WhatsApp</h3>
                    {conversation?.messages?.length ? (
                      <div className="message-thread compact-thread">
                        {conversation.messages.slice(-6).map((message) => (
                          <div key={message.id} className={`message-bubble ${message.sender_type === 'business' ? 'message-outbound' : 'message-inbound'}`}>
                            <strong>{message.sender_type === 'business' ? 'Operatore' : 'Cliente'}</strong>
                            <p>{message.content || 'Messaggio vuoto'}</p>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p>Nessuna chat WhatsApp disponibile.</p>
                    )}
                    {selectedCustomer?.phone && (
                      <div className="reply-box">
                        <textarea
                          value={replyBody}
                          onChange={(e) => setReplyBody(e.target.value)}
                          placeholder="Invia un aggiornamento al cliente"
                        />
                        <button onClick={sendReply}>Invia</button>
                      </div>
                    )}
                  </article>
                </>
              )}
            </section>
          </>
        )}

        {token && page === 'calendar' && (
          <section className="list-panel full-width">
            <div className="section-heading">
              <div>
                <h2>Calendario interventi</h2>
                <p>Vista semplificata degli appuntamenti generati dopo l'accettazione.</p>
              </div>
            </div>
            <div className="schedule-list">
              {appointments.length === 0 ? (
                <p>Nessun appuntamento disponibile.</p>
              ) : appointments.map((appointment) => (
                <article key={appointment.id} className="schedule-card">
                  <strong>{formatDate(appointment.start_datetime)}</strong>
                  <p>{appointment.address || 'Indirizzo da confermare'}</p>
                  <span className="status-badge">{appointment.status || 'PROPOSTO'}</span>
                </article>
              ))}
            </div>
          </section>
        )}

        {token && page === 'settings' && (
          <section className="list-panel full-width">
            <h2>Impostazioni</h2>
            <div className="settings-grid">
              <article className="detail-card">
                <h3>Profilo</h3>
                <p>{currentUser?.first_name} {currentUser?.last_name}</p>
                <p>{currentUser?.email}</p>
              </article>
              <article className="detail-card">
                <h3>Canali</h3>
                <p>WhatsApp integrato tramite Twilio.</p>
                <p>Webhook attivo sul backend.</p>
              </article>
            </div>
          </section>
        )}
      </main>
      {token && (
        <nav className="bottom-nav" aria-label="Navigazione principale">
          <button className={page === 'dashboard' ? 'bottom-nav-active' : ''} onClick={() => setPage('dashboard')}><Home size={20} /><span>Home</span></button>
          <button className={page === 'requests' || page === 'request-detail' ? 'bottom-nav-active' : ''} onClick={() => setPage('requests')}><ClipboardList size={20} /><span>Richieste</span></button>
          <button className={page === 'calendar' ? 'bottom-nav-active' : ''} onClick={() => setPage('calendar')}><CalendarDays size={20} /><span>Calendario</span></button>
          <button className={page === 'customers' ? 'bottom-nav-active' : ''} onClick={() => setPage('customers')}><Users size={20} /><span>Clienti</span></button>
          <button className={page === 'settings' ? 'bottom-nav-active' : ''} onClick={() => setPage('settings')}><MoreHorizontal size={20} /><span>Altro</span></button>
        </nav>
      )}
    </div>
  );
}

export default App;
