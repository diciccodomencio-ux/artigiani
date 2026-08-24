import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  CalendarClock,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Clock3,
  Home,
  ImageIcon,
  Map as MapIcon,
  MapPin,
  MoreHorizontal,
  Navigation,
  Phone,
  Play,
  RefreshCw,
  Route,
  Sparkles,
  Timer,
  Users,
  Wrench,
  X,
} from 'lucide-react';
import './index.css';

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';
const LEAFLET_VERSION = '1.9.4';

const STATUS_LABELS = {
  NUOVA: 'Nuova',
  IN_RACCOLTA_DATI: 'Raccolta dati',
  DA_VALUTARE: 'Da valutare',
  ACCETTATA: 'Accettata',
  PROGRAMMATA: 'Programmata',
  IN_CORSO: 'In corso',
  COMPLETATA: 'Completata',
  RIFIUTATA: 'Rifiutata',
  ANNULLATA: 'Annullata',
  IN_ATTESA_CLIENTE: 'In attesa cliente',
};

const URGENCY_LABELS = {
  alta: 'Alta',
  media: 'Media',
  bassa: 'Bassa',
};

let leafletPromise;

function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (leafletPromise) return leafletPromise;

  leafletPromise = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-artigianai-leaflet]')) {
      const stylesheet = document.createElement('link');
      stylesheet.rel = 'stylesheet';
      stylesheet.href = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.css`;
      stylesheet.dataset.artigianaiLeaflet = 'true';
      document.head.appendChild(stylesheet);
    }

    const existing = document.querySelector('script[data-artigianai-leaflet]');
    if (existing) {
      existing.addEventListener('load', () => resolve(window.L), { once: true });
      existing.addEventListener('error', reject, { once: true });
      return;
    }

    const script = document.createElement('script');
    script.src = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js`;
    script.dataset.artigianaiLeaflet = 'true';
    script.onload = () => resolve(window.L);
    script.onerror = reject;
    document.body.appendChild(script);
  });

  return leafletPromise;
}

function PlannerMap({ points, routeGeometry }) {
  const elementRef = useRef(null);
  const mapInstanceRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function renderMap() {
      if (!elementRef.current || !points.length) return;

      try {
        const L = await loadLeaflet();
        if (cancelled || !elementRef.current) return;

        if (mapInstanceRef.current) {
          mapInstanceRef.current.remove();
          mapInstanceRef.current = null;
        }

        const map = L.map(elementRef.current, {
          zoomControl: true,
          attributionControl: true,
        });
        mapInstanceRef.current = map;

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap contributors',
        }).addTo(map);

        const bounds = [];
        points.forEach((point, index) => {
          const order = point.order ?? index + 1;
          const icon = L.divIcon({
            className: 'planner-pin-wrapper',
            html: `<span class="planner-pin"><b>${order}</b></span>`,
            iconSize: [34, 34],
            iconAnchor: [17, 17],
          });

          const marker = L.marker([point.lat, point.lng], { icon }).addTo(map);
          marker.bindPopup(
            `<strong>${escapeHtml(point.title || `Intervento ${order}`)}</strong><br/>${escapeHtml(point.address || '')}`,
          );
          bounds.push([point.lat, point.lng]);
        });

        if (routeGeometry?.length) {
          const routeLayer = L.geoJSON({
            type: 'Feature',
            geometry: {
              type: 'LineString',
              coordinates: routeGeometry,
            },
          }, {
            style: { color: '#d66a18', weight: 5, opacity: 0.8 },
          }).addTo(map);
          const routeBounds = routeLayer.getBounds();
          if (routeBounds.isValid()) map.fitBounds(routeBounds, { padding: [26, 26] });
        } else if (bounds.length === 1) {
          map.setView(bounds[0], 14);
        } else {
          map.fitBounds(bounds, { padding: [30, 30] });
        }
      } catch (err) {
        console.error('Map loading error', err);
      }
    }

    renderMap();

    return () => {
      cancelled = true;
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, [points, routeGeometry]);

  if (!points.length) {
    return (
      <div className="map-empty">
        <MapPin size={26} />
        <strong>Nessun intervento geolocalizzato</strong>
        <span>Premi “Geolocalizza” per trasformare gli indirizzi in punti sulla mappa.</span>
      </div>
    );
  }

  return <div ref={elementRef} className="planner-map" aria-label="Mappa interventi" />;
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function localDateKey(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function toDateTimeLocal(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function nextPlanningSlot() {
  const now = new Date();
  now.setSeconds(0, 0);
  const minutes = now.getMinutes();
  const add = minutes === 0 ? 60 : 60 - minutes;
  now.setMinutes(minutes + add);
  if (now.getHours() >= 19) {
    now.setDate(now.getDate() + 1);
    now.setHours(9, 0, 0, 0);
  }
  return toDateTimeLocal(now);
}

function startOfWeek(value) {
  const date = new Date(`${value}T12:00:00`);
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  date.setHours(0, 0, 0, 0);
  return date;
}

function minutesBetween(start, end) {
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return 0;
  return Math.max(0, Math.round((endDate - startDate) / 60000));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

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

  const [calendarView, setCalendarView] = useState('today');
  const [calendarDate, setCalendarDate] = useState(localDateKey(new Date()));
  const [scheduleStart, setScheduleStart] = useState(nextPlanningSlot());
  const [scheduleDuration, setScheduleDuration] = useState(60);
  const [durationEstimate, setDurationEstimate] = useState(null);
  const [geocoding, setGeocoding] = useState(false);
  const [mapMessage, setMapMessage] = useState('');
  const [routeLoading, setRouteLoading] = useState(false);
  const [routeSummary, setRouteSummary] = useState(null);

  useEffect(() => {
    if (token) {
      Promise.all([
        fetchMe(),
        fetchDashboard(),
        fetchRequests(),
        fetchCustomers(),
        fetchUsers(),
        fetchAppointments(),
      ]).catch((err) => setError(err.message));
    } else {
      setPage('login');
    }
  }, [token]);

  useEffect(() => {
    setRouteSummary(null);
  }, [calendarDate]);

  const appointmentByRequestId = useMemo(() => {
    const map = new Map();
    appointments.forEach((appointment) => {
      if (appointment.service_request_id) map.set(appointment.service_request_id, appointment);
    });
    return map;
  }, [appointments]);

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

  const unscheduledRequests = useMemo(() => requests
    .filter((item) => ['ACCETTATA', 'PROGRAMMATA'].includes(item.status) && !appointmentByRequestId.has(item.id))
    .sort((a, b) => {
      const urgencyRank = { alta: 0, media: 1, bassa: 2 };
      return (urgencyRank[a.urgency] ?? 1) - (urgencyRank[b.urgency] ?? 1);
    }), [requests, appointmentByRequestId]);

  const selectedDayAppointments = useMemo(() => appointments
    .filter((appointment) => localDateKey(appointment.start_datetime) === calendarDate)
    .sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime)), [appointments, calendarDate]);

  const weekDays = useMemo(() => {
    const monday = startOfWeek(calendarDate);
    return Array.from({ length: 7 }, (_, index) => {
      const date = new Date(monday);
      date.setDate(monday.getDate() + index);
      return date;
    });
  }, [calendarDate]);

  const selectedDayPoints = useMemo(() => {
    return selectedDayAppointments
      .map((appointment, index) => {
        const requestItem = requests.find((item) => item.id === appointment.service_request_id);
        if (!requestItem || requestItem.latitude == null || requestItem.longitude == null) return null;
        return {
          appointmentId: appointment.id,
          requestId: requestItem.id,
          lat: Number(requestItem.latitude),
          lng: Number(requestItem.longitude),
          order: index + 1,
          title: `${formatTime(appointment.start_datetime)} · ${customerName(requestItem.customer)}`,
          address: fullAddress(requestItem),
          appointment,
          request: requestItem,
        };
      })
      .filter(Boolean);
  }, [selectedDayAppointments, requests]);

  const mapPoints = routeSummary?.orderedPoints?.length
    ? routeSummary.orderedPoints.map((point, index) => ({ ...point, order: index + 1 }))
    : selectedDayPoints;

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

  function fullAddress(requestItem) {
    return [requestItem?.address, requestItem?.city].filter(Boolean).join(', ') || 'Indirizzo da confermare';
  }

  function formatDate(value) {
    if (!value) return 'N/D';
    return new Date(value).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' });
  }

  function formatTime(value) {
    if (!value) return '--:--';
    return new Date(value).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  }

  function formatDay(value) {
    return new Date(value).toLocaleDateString('it-IT', {
      weekday: 'short',
      day: '2-digit',
      month: 'short',
    });
  }

  function attachmentHref(fileUrl) {
    if (!fileUrl) return '#';
    if (fileUrl.startsWith('http://') || fileUrl.startsWith('https://')) return fileUrl;
    return `${API_URL.replace('/api', '')}${fileUrl}`;
  }

  function requestSummary(item) {
    return STATUS_LABELS[item?.status] || item?.status || 'In lavorazione';
  }

  function userLabel(user) {
    return [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email;
  }

  function requestForAppointment(appointment) {
    return requests.find((item) => item.id === appointment.service_request_id);
  }

  function currentAppointmentForRequest(requestId) {
    return appointmentByRequestId.get(requestId);
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
      setCurrentUser(await res.json());
    } catch {
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

  async function doLogin(event) {
    event.preventDefault();
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
    try {
      const res = await fetch(`${API_URL}/requests`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Impossibile caricare le richieste');
      const data = await res.json();
      setRequests(data);
      setSelected((current) => {
        if (!current) return data[0] || null;
        return data.find((item) => item.id === current.id) || current;
      });
      return data;
    } catch (err) {
      setError(err.message);
      return [];
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
    const data = await res.json();
    setAppointments(data);
    return data;
  }

  async function fetchDurationEstimate(requestId) {
    try {
      const res = await fetch(`${API_URL}/requests/${requestId}/duration-estimate`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return null;
      const estimate = await res.json();
      setDurationEstimate(estimate);
      setScheduleDuration(estimate.estimated_duration_minutes || 60);
      return estimate;
    } catch {
      return null;
    }
  }

  async function openRequest(requestItem) {
    setSelected(requestItem);
    setAssigneeId(requestItem?.assigned_user_id ? String(requestItem.assigned_user_id) : '');
    setPage('request-detail');
    setAttachments([]);
    setDurationEstimate(null);

    const existingAppointment = currentAppointmentForRequest(requestItem.id);
    if (existingAppointment) {
      setScheduleStart(toDateTimeLocal(existingAppointment.start_datetime));
      setScheduleDuration(minutesBetween(existingAppointment.start_datetime, existingAppointment.end_datetime) || 60);
    } else {
      setScheduleStart(nextPlanningSlot());
      setScheduleDuration(requestItem.estimated_duration_minutes || 60);
    }

    if (requestItem?.customer_id) {
      await openCustomer(requestItem.customer_id);
    } else {
      setSelectedCustomer(null);
      setCustomerHistory(null);
      setConversation(null);
    }

    const [attachmentRes] = await Promise.all([
      fetch(`${API_URL}/requests/${requestItem.id}/attachments`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
      fetchDurationEstimate(requestItem.id),
    ]);

    if (attachmentRes.ok) setAttachments(await attachmentRes.json());
  }

  async function openCustomer(customerId) {
    const [customerRes, historyRes, conversationRes] = await Promise.all([
      fetch(`${API_URL}/customers/${customerId}`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/customers/${customerId}/history`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/customers/${customerId}/conversation`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    if (customerRes.ok) setSelectedCustomer(await customerRes.json());
    if (historyRes.ok) setCustomerHistory(await historyRes.json());
    if (conversationRes.ok) setConversation(await conversationRes.json());
    else setConversation(null);
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
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || 'Errore accettazione');
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
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || 'Errore rifiuto');
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
        const body = await res.json();
        throw new Error(body.detail || 'Errore assegnazione');
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

  async function scheduleRequest(id) {
    if (!scheduleStart) {
      setError('Seleziona giorno e ora dell’intervento');
      return;
    }

    const duration = Number(scheduleDuration);
    if (!duration || duration <= 0) {
      setError('La durata deve essere maggiore di zero');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const payload = {
        start_datetime: scheduleStart,
        duration_minutes: duration,
        assigned_user_id: assigneeId ? Number(assigneeId) : selected?.assigned_user_id || null,
        notes: 'Orario concordato con il cliente',
      };

      const res = await fetch(`${API_URL}/requests/${id}/schedule`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || 'Errore pianificazione');
      }

      await res.json();
      setSelected((current) => current?.id === id ? { ...current, status: 'PROGRAMMATA', estimated_duration_minutes: duration } : current);
      setCalendarDate(scheduleStart.slice(0, 10));
      await Promise.all([fetchRequests(), fetchDashboard(), fetchAppointments()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function startRequest(id) {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/requests/${id}/start`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || 'Errore avvio intervento');
      }
      const updated = await res.json();
      if (selected?.id === id) setSelected(updated);
      await Promise.all([fetchRequests(), fetchDashboard(), fetchAppointments()]);
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
        const body = await res.json();
        throw new Error(body.detail || 'Errore completamento');
      }
      const updated = await res.json();
      if (selected?.id === id) setSelected(updated);
      await Promise.all([fetchRequests(), fetchDashboard(), fetchAppointments()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function geocodeSingleRequest(requestItem) {
    if (requestItem.latitude != null && requestItem.longitude != null) return requestItem;
    if (!requestItem.address && !requestItem.city) return requestItem;

    const query = [requestItem.address, requestItem.city, 'Italia'].filter(Boolean).join(', ');
    const geocodeUrl = `https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&accept-language=it&q=${encodeURIComponent(query)}`;
    const geocodeRes = await fetch(geocodeUrl);
    if (!geocodeRes.ok) return requestItem;
    const matches = await geocodeRes.json();
    if (!matches.length) return requestItem;

    const latitude = Number(matches[0].lat);
    const longitude = Number(matches[0].lon);
    const persistRes = await fetch(`${API_URL}/requests/${requestItem.id}/location`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ latitude, longitude }),
    });

    if (!persistRes.ok) return { ...requestItem, latitude, longitude };
    return await persistRes.json();
  }

  async function geocodePlannerRequests() {
    const relevantRequestIds = new Set([
      ...selectedDayAppointments.map((item) => item.service_request_id),
      ...unscheduledRequests.map((item) => item.id),
    ].filter(Boolean));

    const targets = requests.filter((item) => relevantRequestIds.has(item.id) && (item.latitude == null || item.longitude == null));
    if (!targets.length) {
      setMapMessage('Gli interventi disponibili sono già geolocalizzati.');
      return;
    }

    setGeocoding(true);
    setMapMessage(`Geolocalizzazione di ${targets.length} indirizzi…`);
    try {
      const updates = [];
      for (let index = 0; index < targets.length; index += 1) {
        const updated = await geocodeSingleRequest(targets[index]);
        updates.push(updated);
        if (index < targets.length - 1) await sleep(1100);
      }

      const byId = new Map(updates.map((item) => [item.id, item]));
      setRequests((current) => current.map((item) => byId.get(item.id) || item));
      setMapMessage('Mappa aggiornata.');
      setRouteSummary(null);
    } catch (err) {
      setMapMessage(`Geolocalizzazione non completata: ${err.message}`);
    } finally {
      setGeocoding(false);
    }
  }

  async function calculateOptimizedRoute() {
    if (selectedDayPoints.length < 2) {
      setMapMessage('Servono almeno due interventi geolocalizzati per calcolare un percorso.');
      return;
    }

    setRouteLoading(true);
    setMapMessage('Calcolo percorso stradale…');
    try {
      const coordinates = selectedDayPoints.map((point) => `${point.lng},${point.lat}`).join(';');
      let url;
      let response;
      let orderedPoints = selectedDayPoints;
      let geometry;
      let distance;
      let duration;

      if (selectedDayPoints.length === 2) {
        url = `https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson`;
        response = await fetch(url);
        if (!response.ok) throw new Error('Servizio percorso non disponibile');
        const data = await response.json();
        const route = data.routes?.[0];
        if (!route) throw new Error('Percorso non trovato');
        geometry = route.geometry?.coordinates || [];
        distance = route.distance;
        duration = route.duration;
      } else {
        url = `https://router.project-osrm.org/trip/v1/driving/${coordinates}?source=first&roundtrip=false&overview=full&geometries=geojson`;
        response = await fetch(url);
        if (!response.ok) throw new Error('Servizio ottimizzazione non disponibile');
        const data = await response.json();
        const trip = data.trips?.[0];
        if (!trip) throw new Error('Percorso non trovato');
        geometry = trip.geometry?.coordinates || [];
        distance = trip.distance;
        duration = trip.duration;

        const inputWaypoints = data.waypoints || [];
        orderedPoints = selectedDayPoints
          .map((point, inputIndex) => ({ point, order: inputWaypoints[inputIndex]?.waypoint_index ?? inputIndex }))
          .sort((a, b) => a.order - b.order)
          .map((entry) => entry.point);
      }

      setRouteSummary({
        orderedPoints,
        geometry,
        distanceKm: Math.round((distance / 1000) * 10) / 10,
        durationMinutes: Math.round(duration / 60),
      });
      setMapMessage('Percorso geografico suggerito pronto. Gli orari confermati non vengono modificati.');
    } catch (err) {
      setMapMessage(`Percorso non disponibile: ${err.message}`);
    } finally {
      setRouteLoading(false);
    }
  }

  function externalRouteHref() {
    const points = routeSummary?.orderedPoints?.length ? routeSummary.orderedPoints : selectedDayPoints;
    if (points.length < 2) return '#';
    const origin = `${points[0].lat},${points[0].lng}`;
    const destination = `${points[points.length - 1].lat},${points[points.length - 1].lng}`;
    const waypoints = points.slice(1, -1).map((point) => `${point.lat},${point.lng}`).join('|');
    const params = new URLSearchParams({ api: '1', origin, destination, travelmode: 'driving' });
    if (waypoints) params.set('waypoints', waypoints);
    return `https://www.google.com/maps/dir/?${params.toString()}`;
  }

  function logout() {
    setToken('');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setRequests([]);
    setAppointments([]);
    setPage('login');
    setCurrentUser(null);
  }

  function renderAppointmentCard(appointment, compact = false) {
    const requestItem = requestForAppointment(appointment);
    const duration = minutesBetween(appointment.start_datetime, appointment.end_datetime);
    const canStart = requestItem && requestItem.status === 'PROGRAMMATA';
    const canComplete = requestItem && ['PROGRAMMATA', 'IN_CORSO'].includes(requestItem.status);

    return (
      <article key={appointment.id} className={`schedule-card planner-appointment ${compact ? 'schedule-card-compact' : ''}`}>
        <div className="schedule-time-block">
          <strong>{formatTime(appointment.start_datetime)}</strong>
          <span>{formatTime(appointment.end_datetime)}</span>
        </div>
        <div className="schedule-main">
          <div className="card-topline">
            <div>
              <h3>{requestItem ? customerName(requestItem.customer) : 'Cliente'}</h3>
              <p>{requestItem?.description || requestItem?.category || 'Intervento'}</p>
            </div>
            <span className="status-badge">{requestSummary(requestItem) || appointment.status}</span>
          </div>
          <span className="schedule-address"><MapPin size={15} /> {requestItem ? fullAddress(requestItem) : appointment.address || 'Indirizzo da confermare'}</span>
          <div className="schedule-meta">
            <span><Timer size={15} /> {duration || requestItem?.estimated_duration_minutes || 60} min</span>
            <span><CalendarClock size={15} /> {appointment.customer_confirmed ? 'Orario confermato' : 'Da confermare'}</span>
            {appointment.actual_duration_minutes ? <span><CheckCircle2 size={15} /> Reale {appointment.actual_duration_minutes} min</span> : null}
          </div>
          {requestItem && (
            <div className="planner-actions">
              <button className="secondary-action" onClick={() => openRequest(requestItem)}>Dettagli</button>
              {canStart && <button className="start-action" onClick={() => startRequest(requestItem.id)}><Play size={16} /> Inizia</button>}
              {canComplete && <button className="complete-action" onClick={() => completeRequest(requestItem.id)}><CheckCircle2 size={16} /> Completa</button>}
            </div>
          )}
        </div>
      </article>
    );
  }

  const pageTitle = page === 'dashboard' && currentUser
    ? `Ciao ${currentUser.first_name}`
    : page === 'request-detail'
      ? 'Dettaglio richiesta'
      : page === 'customers'
        ? 'Clienti'
        : page === 'settings'
          ? 'Profilo'
          : page === 'requests'
            ? 'Richieste'
            : page === 'calendar'
              ? 'Agenda'
              : 'ArtigianAI';

  return (
    <div className={`app-shell ${page === 'dashboard' ? 'dashboard-shell' : ''}`}>
      <header className="topbar">
        <div>
          <p className="eyebrow">ArtigianAI</p>
          <h1>{pageTitle}</h1>
          {currentUser && page === 'dashboard' && <p className="subcopy">Ecco il riepilogo operativo di oggi.</p>}
          {currentUser && page === 'calendar' && <p className="subcopy">Orari confermati, attività da fare e percorso della giornata.</p>}
        </div>
        {token && page === 'request-detail' && (
          <button className="icon-button" aria-label="Torna alle richieste" onClick={() => setPage('requests')}>
            <ArrowLeft size={20} />
          </button>
        )}
      </header>

      <main>
        {page === 'login' && (
          <section className="form-panel">
            <h2>Login</h2>
            <form onSubmit={doLogin}>
              <label>
                Email
                <input value={email} onChange={(event) => setEmail(event.target.value)} required />
              </label>
              <label>
                Password
                <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
              </label>
              <button type="submit">Accedi</button>
            </form>
            {loading && <p>Caricamento...</p>}
            {error && <p className="error">{error}</p>}
          </section>
        )}

        {token && error && page !== 'login' && <div className="global-error">{error}</div>}

        {token && page === 'dashboard' && (
          <>
            <section className="dashboard-grid">
              <article className="metric-card metric-highlight">
                <span>Nuove richieste</span>
                <strong>{dashboard?.new_requests ?? 0}</strong>
              </article>
              <article className="metric-card metric-highlight">
                <span>Oggi</span>
                <strong>{appointments.filter((item) => localDateKey(item.start_datetime) === localDateKey(new Date())).length}</strong>
              </article>
              <article className="metric-card">
                <span>Da pianificare</span>
                <strong>{unscheduledRequests.length}</strong>
              </article>
              <article className="metric-card">
                <span>Completati</span>
                <strong>{dashboard?.completed_requests ?? 0}</strong>
              </article>
            </section>

            <section className="list-panel">
              <div className="section-heading">
                <div>
                  <h2>Agenda di oggi</h2>
                  <p>Interventi ordinati per orario.</p>
                </div>
                <button className="text-action" onClick={() => { setCalendarDate(localDateKey(new Date())); setCalendarView('today'); setPage('calendar'); }}>Apri agenda</button>
              </div>
              <div className="schedule-list dashboard-agenda">
                {appointments.filter((item) => localDateKey(item.start_datetime) === localDateKey(new Date())).length === 0 ? (
                  <p>Nessun intervento programmato oggi.</p>
                ) : appointments
                  .filter((item) => localDateKey(item.start_datetime) === localDateKey(new Date()))
                  .sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime))
                  .slice(0, 3)
                  .map((item) => renderAppointmentCard(item, true))}
              </div>
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
                      <span className="request-location"><MapPin size={15} /> {fullAddress(requestItem)}</span>
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
                <p>Gestisci la coda e porta ogni richiesta fino all'appuntamento.</p>
              </div>
              <button onClick={() => Promise.all([fetchRequests(), fetchAppointments()])}><RefreshCw size={16} /> Aggiorna</button>
            </div>
            <div className="filters-row">
              <input
                placeholder="Cerca cliente, problema o città"
                value={filters.search}
                onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
              />
              <select value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
                <option value="all">Tutti gli stati</option>
                <option value="NUOVA">Nuove</option>
                <option value="ACCETTATA">Da pianificare</option>
                <option value="PROGRAMMATA">Programmate</option>
                <option value="IN_CORSO">In corso</option>
                <option value="COMPLETATA">Completate</option>
                <option value="RIFIUTATA">Rifiutate</option>
              </select>
            </div>
            <div className="request-tabs" aria-label="Filtra richieste per stato">
              {[
                ['all', 'Tutte'],
                ['NUOVA', 'Nuove'],
                ['ACCETTATA', 'Da pianificare'],
                ['PROGRAMMATA', 'Programmate'],
                ['IN_CORSO', 'In corso'],
                ['COMPLETATA', 'Completate'],
              ].map(([status, label]) => (
                <button key={status} className={filters.status === status ? 'tab-active' : ''} onClick={() => setFilters((prev) => ({ ...prev, status }))}>{label}</button>
              ))}
            </div>

            {filteredRequests.length === 0 ? (
              <p>Nessuna richiesta trovata.</p>
            ) : (
              <div className="request-list">
                {filteredRequests.map((requestItem) => {
                  const appointment = currentAppointmentForRequest(requestItem.id);
                  return (
                    <article key={requestItem.id} className={`request-card ${selected?.id === requestItem.id ? 'selected-card' : ''}`}>
                      <div className="card-topline">
                        <span className="status-badge">{requestSummary(requestItem)}</span>
                        <span className="muted">{appointment ? `${formatDay(appointment.start_datetime)} · ${formatTime(appointment.start_datetime)}` : formatDate(requestItem.created_at)}</span>
                      </div>
                      <h3>{requestItem.category || 'Nuova richiesta'} · {requestItem.city || 'Città da confermare'}</h3>
                      <p>{customerName(requestItem.customer)}</p>
                      <p>{requestItem.description}</p>
                      <div className="card-meta">
                        <span>{URGENCY_LABELS[requestItem.urgency] || requestItem.urgency || 'Media'}</span>
                        <span>{requestItem.estimated_duration_minutes ? `~ ${requestItem.estimated_duration_minutes} min` : 'Durata da stimare'}</span>
                      </div>
                      <div className="actions">
                        <button className="secondary-action" onClick={() => openRequest(requestItem)}>Dettaglio <ChevronRight size={17} /></button>
                        {requestItem.status === 'NUOVA' && <button className="accept-action" onClick={() => acceptRequest(requestItem.id)}><Check size={18} /> Accetta</button>}
                        {['ACCETTATA', 'PROGRAMMATA'].includes(requestItem.status) && <button className="schedule-action" onClick={() => openRequest(requestItem)}><CalendarClock size={17} /> Pianifica</button>}
                        {requestItem.status === 'PROGRAMMATA' && <button className="start-action" onClick={() => startRequest(requestItem.id)}><Play size={17} /> Inizia</button>}
                        {requestItem.status === 'IN_CORSO' && <button className="complete-action" onClick={() => completeRequest(requestItem.id)}><CheckCircle2 size={17} /> Completa</button>}
                        {requestItem.status === 'NUOVA' && <button className="reject-action" onClick={() => rejectRequest(requestItem.id)}><X size={18} /> Rifiuta</button>}
                      </div>
                    </article>
                  );
                })}
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
                    <h2>{selected.description || selected.category || 'Richiesta'}</h2>
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
                    <div><span>Indirizzo</span><strong>{fullAddress(selected)}</strong></div>
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

                <article className="detail-card planning-card">
                  <div className="section-heading">
                    <div>
                      <h3>Pianifica intervento</h3>
                      <p>L'orario salvato viene comunicato al cliente e resta stabile finché non lo modifichi.</p>
                    </div>
                    <Sparkles size={21} />
                  </div>

                  <div className="estimate-box">
                    <div>
                      <span>Durata prevista</span>
                      <strong>{durationEstimate?.estimated_duration_minutes || selected.estimated_duration_minutes || scheduleDuration} min</strong>
                    </div>
                    <div>
                      <span>Confidenza</span>
                      <strong>{durationEstimate?.confidence || 'bassa'}</strong>
                    </div>
                    <div>
                      <span>Casi simili</span>
                      <strong>{durationEstimate?.sample_count ?? 0}</strong>
                    </div>
                  </div>

                  <div className="planning-fields">
                    <label>
                      Giorno e ora
                      <input type="datetime-local" value={scheduleStart} onChange={(event) => setScheduleStart(event.target.value)} />
                    </label>
                    <label>
                      Durata
                      <select value={scheduleDuration} onChange={(event) => setScheduleDuration(Number(event.target.value))}>
                        {[30, 45, 60, 75, 90, 120, 150, 180, 240].map((minutes) => <option key={minutes} value={minutes}>{minutes} min</option>)}
                      </select>
                    </label>
                  </div>

                  <div className="assignment-row planning-assignee">
                    <select value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}>
                      <option value="">Tecnico non assegnato</option>
                      {users.map((user) => <option key={user.id} value={user.id}>{userLabel(user)} · {user.role}</option>)}
                    </select>
                    <button className="schedule-action" onClick={() => scheduleRequest(selected.id)}><CalendarClock size={17} /> {currentAppointmentForRequest(selected.id) ? 'Aggiorna orario' : 'Conferma appuntamento'}</button>
                  </div>

                  {currentAppointmentForRequest(selected.id) && (
                    <div className="confirmed-slot">
                      <CheckCircle2 size={18} />
                      <div>
                        <strong>Orario confermato</strong>
                        <span>{formatDay(currentAppointmentForRequest(selected.id).start_datetime)} · {formatTime(currentAppointmentForRequest(selected.id).start_datetime)}–{formatTime(currentAppointmentForRequest(selected.id).end_datetime)}</span>
                      </div>
                    </div>
                  )}
                </article>

                <article className="detail-card">
                  <div className="section-heading">
                    <div>
                      <h3>Foto WhatsApp</h3>
                      <p>{attachments.length ? `${attachments.length} allegati ricevuti dal cliente` : 'Nessuna foto ricevuta.'}</p>
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

                <article className="detail-card">
                  <h3>Azioni intervento</h3>
                  <div className="request-action-bar planner-detail-actions">
                    {selected.status === 'NUOVA' && <button className="accept-action" onClick={() => acceptRequest(selected.id)}><Check size={18} /> Accetta</button>}
                    {selected.status === 'PROGRAMMATA' && <button className="start-action" onClick={() => startRequest(selected.id)}><Play size={18} /> Inizia</button>}
                    {['PROGRAMMATA', 'IN_CORSO'].includes(selected.status) && <button className="complete-action" onClick={() => completeRequest(selected.id)}><CheckCircle2 size={18} /> Completa</button>}
                    {selectedCustomer?.phone ? <a className="call-action" href={`tel:${selectedCustomer.phone.replace(/\s/g, '')}`}><Phone size={18} /> Chiama</a> : null}
                    {selected.status === 'NUOVA' && <button className="reject-action" onClick={() => rejectRequest(selected.id)}><X size={18} /> Rifiuta</button>}
                  </div>
                </article>

                <article className="detail-card">
                  <div className="section-heading">
                    <div>
                      <h3>Assegna tecnico</h3>
                      <p>L'assegnazione non sostituisce la pianificazione dell'orario.</p>
                    </div>
                  </div>
                  <div className="assignment-row">
                    <select value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)}>
                      <option value="">Seleziona un tecnico</option>
                      {users.map((user) => <option key={user.id} value={user.id}>{userLabel(user)} · {user.role}</option>)}
                    </select>
                    <button onClick={() => assignRequest(selected.id)}>Assegna</button>
                  </div>
                </article>

                <article className="detail-card">
                  <h3>Storico cliente</h3>
                  {customerHistory?.service_requests?.length ? (
                    <div className="history-list">
                      {customerHistory.service_requests.slice(0, 5).map((item) => (
                        <div key={item.id} className="history-row">
                          <strong>{item.category || 'Intervento'}</strong>
                          <span>{requestSummary(item)} · {formatDate(item.created_at)}</span>
                        </div>
                      ))}
                    </div>
                  ) : <p>Nessuno storico disponibile.</p>}
                </article>

                <article className="detail-card">
                  <div className="section-heading">
                    <div>
                      <h3>Conversazione WhatsApp</h3>
                      <p>Replica direttamente al cliente.</p>
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
                  ) : <p>Nessuna conversazione WhatsApp disponibile per questo cliente.</p>}
                  {selectedCustomer?.phone && (
                    <div className="reply-box">
                      <textarea value={replyBody} onChange={(event) => setReplyBody(event.target.value)} placeholder="Scrivi una risposta WhatsApp per il cliente" />
                      <button onClick={sendReply}>Invia risposta</button>
                    </div>
                  )}
                </article>
              </>
            )}
          </section>
        )}

        {token && page === 'calendar' && (
          <section className="list-panel full-width calendar-workspace">
            <div className="calendar-toolbar">
              <div className="calendar-view-tabs">
                <button className={calendarView === 'today' ? 'tab-active' : ''} onClick={() => setCalendarView('today')}><Clock3 size={16} /> Oggi</button>
                <button className={calendarView === 'week' ? 'tab-active' : ''} onClick={() => setCalendarView('week')}><CalendarDays size={16} /> Settimana</button>
                <button className={calendarView === 'map' ? 'tab-active' : ''} onClick={() => setCalendarView('map')}><MapIcon size={16} /> Mappa</button>
              </div>
              <div className="calendar-date-control">
                <input type="date" value={calendarDate} onChange={(event) => setCalendarDate(event.target.value)} />
                <button className="secondary-action" onClick={() => setCalendarDate(localDateKey(new Date()))}>Oggi</button>
              </div>
            </div>

            {unscheduledRequests.length > 0 && (
              <section className="planner-section unscheduled-section">
                <div className="section-heading">
                  <div>
                    <h2>Da pianificare</h2>
                    <p>Richieste accettate senza un orario fissato.</p>
                  </div>
                  <span className="counter-pill">{unscheduledRequests.length}</span>
                </div>
                <div className="unscheduled-grid">
                  {unscheduledRequests.map((requestItem) => (
                    <article key={requestItem.id} className="unscheduled-card">
                      <div>
                        <span className={`urgency-dot urgency-${requestItem.urgency || 'media'}`} />
                        <strong>{customerName(requestItem.customer)}</strong>
                      </div>
                      <p>{requestItem.description || requestItem.category || 'Intervento'}</p>
                      <span><MapPin size={14} /> {fullAddress(requestItem)}</span>
                      <span><Timer size={14} /> {requestItem.estimated_duration_minutes || 60} min stimati</span>
                      <button onClick={() => openRequest(requestItem)}><CalendarClock size={16} /> Pianifica</button>
                    </article>
                  ))}
                </div>
              </section>
            )}

            {calendarView === 'today' && (
              <section className="planner-section">
                <div className="section-heading">
                  <div>
                    <h2>{new Date(`${calendarDate}T12:00:00`).toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' })}</h2>
                    <p>{selectedDayAppointments.length} interventi · {selectedDayAppointments.reduce((sum, item) => sum + minutesBetween(item.start_datetime, item.end_datetime), 0)} min pianificati</p>
                  </div>
                </div>
                <div className="schedule-list timeline-list">
                  {selectedDayAppointments.length === 0 ? <p>Nessun intervento programmato per questa giornata.</p> : selectedDayAppointments.map((item) => renderAppointmentCard(item))}
                </div>
              </section>
            )}

            {calendarView === 'week' && (
              <section className="planner-section week-grid">
                {weekDays.map((day) => {
                  const key = localDateKey(day);
                  const dayAppointments = appointments
                    .filter((item) => localDateKey(item.start_datetime) === key)
                    .sort((a, b) => new Date(a.start_datetime) - new Date(b.start_datetime));
                  return (
                    <article key={key} className={`week-day ${key === calendarDate ? 'week-day-selected' : ''}`} onClick={() => setCalendarDate(key)}>
                      <header>
                        <strong>{formatDay(day)}</strong>
                        <span>{dayAppointments.length}</span>
                      </header>
                      {dayAppointments.length === 0 ? <p>Libero</p> : dayAppointments.map((appointment) => {
                        const requestItem = requestForAppointment(appointment);
                        return (
                          <button key={appointment.id} className="week-slot" onClick={(event) => { event.stopPropagation(); if (requestItem) openRequest(requestItem); }}>
                            <strong>{formatTime(appointment.start_datetime)}</strong>
                            <span>{requestItem ? customerName(requestItem.customer) : 'Intervento'}</span>
                          </button>
                        );
                      })}
                    </article>
                  );
                })}
              </section>
            )}

            {calendarView === 'map' && (
              <section className="planner-section map-workspace">
                <div className="map-toolbar">
                  <div>
                    <h2>Mappa della giornata</h2>
                    <p>Gli orari confermati restano fissi. Il percorso suggerito serve a ridurre gli spostamenti.</p>
                  </div>
                  <div className="map-actions">
                    <button className="secondary-action" disabled={geocoding} onClick={geocodePlannerRequests}><MapPin size={16} /> {geocoding ? 'Geolocalizzo…' : 'Geolocalizza'}</button>
                    <button className="schedule-action" disabled={routeLoading || selectedDayPoints.length < 2} onClick={calculateOptimizedRoute}><Route size={16} /> {routeLoading ? 'Calcolo…' : 'Percorso suggerito'}</button>
                    {selectedDayPoints.length >= 2 && <a className="external-route" href={externalRouteHref()} target="_blank" rel="noreferrer"><Navigation size={16} /> Naviga</a>}
                  </div>
                </div>

                {mapMessage && <div className="map-message">{mapMessage}</div>}

                {routeSummary && (
                  <div className="route-summary">
                    <div><span>Distanza</span><strong>{routeSummary.distanceKm} km</strong></div>
                    <div><span>Guida</span><strong>~ {routeSummary.durationMinutes} min</strong></div>
                    <div><span>Interventi</span><strong>{routeSummary.orderedPoints.length}</strong></div>
                  </div>
                )}

                <PlannerMap points={mapPoints} routeGeometry={routeSummary?.geometry || []} />

                {mapPoints.length > 0 && (
                  <div className="route-order-list">
                    <h3>{routeSummary ? 'Ordine geografico suggerito' : 'Ordine per orario'}</h3>
                    {mapPoints.map((point, index) => (
                      <div key={point.appointmentId} className="route-order-row">
                        <span className="route-number">{index + 1}</span>
                        <div>
                          <strong>{point.title}</strong>
                          <span>{point.address}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
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
              {!selectedCustomer ? <p>Seleziona un cliente per vederne il profilo.</p> : (
                <>
                  <h2>{customerName(selectedCustomer)}</h2>
                  <p>{selectedCustomer.phone || 'Telefono non disponibile'}</p>
                  <p>{selectedCustomer.email || 'Email non disponibile'}</p>
                  <p>{selectedCustomer.address || 'Indirizzo non disponibile'}</p>
                  <article className="detail-card">
                    <h3>Richieste recenti</h3>
                    {customerHistory?.service_requests?.length ? customerHistory.service_requests.map((item) => (
                      <div key={item.id} className="history-row"><strong>{item.category || 'Intervento'}</strong><span>{requestSummary(item)} · {formatDate(item.created_at)}</span></div>
                    )) : <p>Nessuna richiesta.</p>}
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
                    ) : <p>Nessuna chat WhatsApp disponibile.</p>}
                    {selectedCustomer?.phone && (
                      <div className="reply-box">
                        <textarea value={replyBody} onChange={(event) => setReplyBody(event.target.value)} placeholder="Invia un aggiornamento al cliente" />
                        <button onClick={sendReply}>Invia</button>
                      </div>
                    )}
                  </article>
                </>
              )}
            </section>
          </>
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
                <p>WhatsApp integrato tramite Meta Cloud API.</p>
                <p>Planner v0.2 attivo.</p>
              </article>
              <article className="detail-card">
                <h3>Sessione</h3>
                <button className="reject-action" onClick={logout}>Esci</button>
              </article>
            </div>
          </section>
        )}
      </main>

      {token && (
        <nav className="bottom-nav" aria-label="Navigazione principale">
          <button className={page === 'dashboard' ? 'bottom-nav-active' : ''} onClick={() => setPage('dashboard')}><Home size={20} /><span>Home</span></button>
          <button className={page === 'requests' || page === 'request-detail' ? 'bottom-nav-active' : ''} onClick={() => setPage('requests')}><ClipboardList size={20} /><span>Richieste</span></button>
          <button className={page === 'calendar' ? 'bottom-nav-active' : ''} onClick={() => setPage('calendar')}><CalendarDays size={20} /><span>Agenda</span></button>
          <button className={page === 'customers' ? 'bottom-nav-active' : ''} onClick={() => setPage('customers')}><Users size={20} /><span>Clienti</span></button>
          <button className={page === 'settings' ? 'bottom-nav-active' : ''} onClick={() => setPage('settings')}><MoreHorizontal size={20} /><span>Altro</span></button>
        </nav>
      )}
    </div>
  );
}

export default App;
