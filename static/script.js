/**
 * static/script.js - Voyage AI Multi-Agent Travel Planner Frontend Logic
 *
 * Responsibilities:
 * 1. View Navigation (Dashboard, New Trip Plan, Saved Trips).
 * 2. Sidebar Collapse/Expand & Responsive Mobile Drawer.
 * 3. Safe JSON API requests with 150-second AbortController timeout.
 * 4. Staged loading indicators with rotating progress messages.
 * 5. Safe, injection-free DOM construction (document.createElement + textContent only).
 * 6. Trip Creation, Real-time Validation, Quick Destination Suggestions.
 * 7. Dedicated Saved Trips catalog with search, filtering, and delete confirmation.
 * 8. Toast feedback notifications.
 */

// =====================================================================
// Global State & Configuration
// =====================================================================

const API_TIMEOUT_MS = 150000; // 150s timeout for multi-agent pipeline

const STAGE_MESSAGES = [
  "Researching top destination attractions and culture...",
  "Curating accommodations and establishing destination currency...",
  "Analyzing transit logistics, passes, and safety tips...",
  "Synthesizing your custom day-by-day master itinerary...",
];

let isSubmitting = false;
let stageIntervalId = null;
let currentSavedTrips = [];
let pendingDeleteTripId = null;
let activeViewName = "dashboard";

// Curated image map for known destinations (with gradient fallback)
const DESTINATION_IMAGES = {
  "kyoto": "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?w=600&auto=format&fit=crop&q=80",
  "rome": "https://images.unsplash.com/photo-1552832230-c0197dd311b5?w=600&auto=format&fit=crop&q=80",
  "banff": "https://images.unsplash.com/photo-1517411032315-54ef2cb783bb?w=600&auto=format&fit=crop&q=80",
  "bali": "https://images.unsplash.com/photo-1537996194471-e657df975ab4?w=600&auto=format&fit=crop&q=80",
  "paris": "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?w=600&auto=format&fit=crop&q=80",
  "seoul": "https://images.unsplash.com/photo-1538485399081-7191377e8241?w=600&auto=format&fit=crop&q=80",
  "costa rica": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600&auto=format&fit=crop&q=80",
  "arenal": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?w=600&auto=format&fit=crop&q=80",
  "tokyo": "https://images.unsplash.com/photo-1503899036084-c55cdd92da26?w=600&auto=format&fit=crop&q=80",
  "london": "https://images.unsplash.com/photo-1513635269975-59663e0ac1ad?w=600&auto=format&fit=crop&q=80",
  "hyderabad": "https://images.unsplash.com/photo-1605647540924-852290f6b0d5?w=600&auto=format&fit=crop&q=80",
  "alps": "https://images.unsplash.com/photo-1530122037265-a5f1f91d3b99?w=600&auto=format&fit=crop&q=80",
  "swiss": "https://images.unsplash.com/photo-1530122037265-a5f1f91d3b99?w=600&auto=format&fit=crop&q=80",
  "grand canyon": "https://images.unsplash.com/photo-1474044159687-1ee9f3a51722?w=600&auto=format&fit=crop&q=80",
  "canyon": "https://images.unsplash.com/photo-1474044159687-1ee9f3a51722?w=600&auto=format&fit=crop&q=80",
  "dubai": "https://images.unsplash.com/photo-1512453979798-5ea266f8880c?w=600&auto=format&fit=crop&q=80",
  "cape town": "https://images.unsplash.com/photo-1580618672591-eb180b1a973f?w=600&auto=format&fit=crop&q=80",
  "new york": "https://images.unsplash.com/photo-1496442226666-8d4d0e62e6e9?w=600&auto=format&fit=crop&q=80",
};

// =====================================================================
// DOM Element References
// =====================================================================

// Sidebar & App Shell
const appSidebar = document.getElementById("app-sidebar");
const sidebarBackdrop = document.getElementById("sidebar-backdrop");
const sidebarCollapseBtn = document.getElementById("sidebar-collapse-btn");
const mobileMenuToggle = document.getElementById("mobile-menu-toggle");
const mobileQuickPlan = document.getElementById("mobile-quick-plan");
const sidebarTripsCount = document.getElementById("sidebar-trips-count");
const dashboardTripsCount = document.getElementById("dashboard-trips-count");
const savedTripsBadge = document.getElementById("saved-trips-badge");

// Navigation buttons
const navDashboard = document.getElementById("nav-dashboard");
const navExplore = document.getElementById("nav-explore");
const navPlanner = document.getElementById("nav-planner");
const navSavedTrips = document.getElementById("nav-saved-trips");

// Views
const viewDashboard = document.getElementById("view-dashboard");
const viewExplore = document.getElementById("view-explore");
const viewPlanner = document.getElementById("view-planner");
const viewSavedTrips = document.getElementById("view-saved-trips");

// Explore View Elements
const exploreSearchInput = document.getElementById("explore-search-input");
const exploreClearSearch = document.getElementById("explore-clear-search");
const exploreFilterCountry = document.getElementById("explore-filter-country");
const exploreFilterCategory = document.getElementById("explore-filter-category");
const exploreFilterBudget = document.getElementById("explore-filter-budget");
const exploreFilterTraveler = document.getElementById("explore-filter-traveler");
const exploreGrid = document.getElementById("explore-grid");
const exploreEmptyState = document.getElementById("explore-empty-state");
const exploreResultsCount = document.getElementById("explore-results-count");
const btnExploreResetFilters = document.getElementById("btn-explore-reset-filters");
const btnExploreToPlanner = document.getElementById("btn-explore-to-planner");
const btnExploreResetEmpty = document.getElementById("btn-explore-reset-empty");
const exploreSelectedBanner = document.getElementById("explore-selected-banner");
const queueCount = document.getElementById("queue-count");
const queueItemsPreview = document.getElementById("queue-items-preview");
const btnClearSelectedAttractions = document.getElementById("btn-clear-selected-attractions");
const btnApplySelectedToPlan = document.getElementById("btn-apply-selected-to-plan");
const btnBrowseCatalogLink = document.getElementById("btn-browse-catalog-link");
const selectedAttractionsContainer = document.getElementById("selected-attractions-container");
const noAttractionsHint = document.getElementById("no-attractions-hint");
const sidebarAttractionsCount = document.getElementById("sidebar-attractions-count");

// Planner Form elements
const plannerForm = document.getElementById("planner-form");
const generateBtn = document.getElementById("generate-btn");
const destinationInput = document.getElementById("destination-input");
const durationInput = document.getElementById("duration-input");
const companionsSelect = document.getElementById("companions-select");
const climateSelect = document.getElementById("climate-select");
const suggestDestBtn = document.getElementById("suggest-dest-btn");
const quickDayChips = document.querySelectorAll(".day-chip");

// Errors & Banners
const destError = document.getElementById("destination-error");
const durationError = document.getElementById("duration-error");
const budgetError = document.getElementById("budget-error");
const interestsError = document.getElementById("interests-error");
const errorBanner = document.getElementById("error-banner");
const errorMessageSpan = document.getElementById("error-message");
const errorDismissBtn = document.getElementById("error-dismiss");
const toastContainer = document.getElementById("toast-container");

// Loading & Itinerary Container
const loadingContainer = document.getElementById("loading-container");
const loadingStageText = document.getElementById("loading-stage-text");
const itineraryView = document.getElementById("itinerary-view");

// Saved Trips Controls
const savedTripsGrid = document.getElementById("saved-trips-grid");
const savedTripsEmpty = document.getElementById("saved-trips-empty");
const savedTripsSearch = document.getElementById("saved-trips-search");
const filterBudget = document.getElementById("filter-budget");
const filterDuration = document.getElementById("filter-duration");
const btnCreateTripShortcut = document.getElementById("btn-create-trip-shortcut");
const btnEmptyStartPlanning = document.getElementById("btn-empty-start-planning");

// Dashboard Shortcuts
const btnHeroPlan = document.getElementById("btn-hero-plan");
const btnHeroExplore = document.getElementById("btn-hero-explore");
const btnHeroSaved = document.getElementById("btn-hero-saved");

// Delete Dialog
const deleteDialog = document.getElementById("delete-confirm-dialog");
const deleteDestName = document.getElementById("delete-destination-name");
const btnCancelDelete = document.getElementById("btn-cancel-delete");
const btnConfirmDelete = document.getElementById("btn-confirm-delete");

// =====================================================================
// View Navigation Router
// =====================================================================

/**
 * Switch the active view between 'dashboard', 'explore', 'planner', and 'saved-trips'.
 *
 * @param {string} viewName - Target view ID suffix.
 * @param {boolean} [updateHash=true] - Whether to push state to location.hash.
 */
function switchView(viewName, updateHash = true) {
  const validViews = ["dashboard", "explore", "planner", "saved-trips"];
  const target = validViews.includes(viewName) ? viewName : "dashboard";
  activeViewName = target;

  // Update Navigation Active States
  [navDashboard, navExplore, navPlanner, navSavedTrips].forEach((btn) => {
    if (!btn) return;
    const isTarget = btn.getAttribute("data-view") === target;
    btn.classList.toggle("active", isTarget);
    if (isTarget) {
      btn.setAttribute("aria-current", "page");
    } else {
      btn.removeAttribute("aria-current");
    }
  });

  // Toggle View Panels
  if (viewDashboard) viewDashboard.hidden = target !== "dashboard";
  if (viewExplore) viewExplore.hidden = target !== "explore";
  if (viewPlanner) viewPlanner.hidden = target !== "planner";
  if (viewSavedTrips) viewSavedTrips.hidden = target !== "saved-trips";

  [viewDashboard, viewExplore, viewPlanner, viewSavedTrips].forEach((viewEl) => {
    if (!viewEl) return;
    viewEl.classList.toggle("active", !viewEl.hidden);
  });

  // Automatically load or refresh data when opening views
  if (target === "saved-trips") {
    loadSavedTrips();
  } else if (target === "explore") {
    loadExploreAttractions();
  }

  // Close mobile drawer if open
  closeMobileDrawer();

  // Update hash if requested
  if (updateHash && window.location.hash !== `#${target}`) {
    window.location.hash = target;
  }

  // Scroll smoothly to top of workspace
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// =====================================================================
// Sidebar & Mobile Drawer Logic
// =====================================================================

function toggleSidebarCollapse() {
  const isCollapsed = document.body.classList.toggle("sidebar-collapsed");
  try {
    localStorage.setItem("voyage_sidebar_collapsed", isCollapsed ? "1" : "0");
  } catch {
    // Ignore localStorage restrictions
  }
}

function openMobileDrawer() {
  if (appSidebar) appSidebar.classList.add("drawer-open");
  if (sidebarBackdrop) sidebarBackdrop.classList.add("active");
  if (mobileMenuToggle) mobileMenuToggle.setAttribute("aria-expanded", "true");
}

function closeMobileDrawer() {
  if (appSidebar) appSidebar.classList.remove("drawer-open");
  if (sidebarBackdrop) sidebarBackdrop.classList.remove("active");
  if (mobileMenuToggle) mobileMenuToggle.setAttribute("aria-expanded", "false");
}

// =====================================================================
// Floating Toasts Notification Helper
// =====================================================================

/**
 * Display a non-intrusive floating toast message in the bottom-right.
 *
 * @param {string} message - Text message.
 * @param {"info" | "success" | "danger"} [type="info"] - Notification category.
 */
function showToast(message, type = "info") {
  if (!toastContainer) return;
  const toast = el("div", `toast ${type === "danger" ? "toast-danger" : ""}`);

  const iconSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  iconSvg.setAttribute("width", "18");
  iconSvg.setAttribute("height", "18");
  iconSvg.setAttribute("viewBox", "0 0 24 24");
  iconSvg.setAttribute("fill", "none");
  iconSvg.setAttribute("stroke", "currentColor");
  iconSvg.setAttribute("stroke-width", "2");

  if (type === "danger") {
    iconSvg.innerHTML = '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line>';
  } else {
    iconSvg.innerHTML = '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>';
  }

  toast.appendChild(iconSvg);
  toast.appendChild(el("span", "", message));
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// =====================================================================
// Safe API Client Helper
// =====================================================================

/**
 * Perform an HTTP request with JSON parsing, network error handling, and timeout.
 *
 * @param {string} url - Target URL.
 * @param {RequestInit} [options={}] - Fetch configuration options.
 * @returns {Promise<any>} The parsed JSON response data.
 */
async function apiRequest(url, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });

    clearTimeout(timeoutId);

    const rawText = await response.text();
    let data = null;
    try {
      data = rawText ? JSON.parse(rawText) : {};
    } catch {
      throw new Error(
        `Server returned an invalid response (HTTP ${response.status}). Please try again later.`
      );
    }

    if (!response.ok) {
      const errMsg =
        data?.error?.message ||
        data?.message ||
        `Request failed with status code ${response.status}.`;
      const err = new Error(errMsg);
      err.status = response.status;
      err.code = data?.error?.code || "HTTP_ERROR";
      err.field = data?.error?.field;
      throw err;
    }

    return data;
  } catch (err) {
    clearTimeout(timeoutId);

    if (err.name === "AbortError") {
      throw new Error(
        "The travel planning request timed out after 150 seconds. Please try again."
      );
    }
    if (err instanceof TypeError && err.message.toLowerCase().includes("fetch")) {
      throw new Error(
        "Network connection error: Unable to reach the Voyage AI server. Please verify your connection."
      );
    }
    throw err;
  }
}

// =====================================================================
// Banner & Field Error Helpers
// =====================================================================

function showErrorBanner(message) {
  if (!errorBanner || !errorMessageSpan) return;
  const cleanMsg = (message || "").trim();
  if (!cleanMsg) {
    hideErrorBanner();
    return;
  }
  errorMessageSpan.textContent = cleanMsg;
  errorBanner.hidden = false;
  errorBanner.classList.remove("hidden");
  errorBanner.classList.add("active");
  errorBanner.style.display = "flex";
  errorBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideErrorBanner() {
  if (!errorBanner) return;
  errorBanner.hidden = true;
  errorBanner.classList.add("hidden");
  errorBanner.classList.remove("active");
  errorBanner.style.display = "none";
  if (errorMessageSpan) {
    errorMessageSpan.textContent = "";
  }
}

function clearFieldErrors() {
  [destError, durationError, budgetError, interestsError].forEach((el) => {
    if (el) {
      el.textContent = "";
      el.classList.remove("active");
    }
  });
}

function setFieldError(fieldElement, message) {
  if (fieldElement) {
    fieldElement.textContent = message;
    fieldElement.classList.add("active");
  }
}

// =====================================================================
// Client-Side Input Validation
// =====================================================================

function isValidDestination(text) {
  if (!text || text.length === 0 || text.length > 160) return false;
  const allowedPattern = /^[\p{L}\p{N}\s,.'()\-&/:+]+$/u;
  return allowedPattern.test(text);
}

function validatePlannerForm() {
  clearFieldErrors();
  let isValid = true;

  // 1. Destination
  const destVal = destinationInput ? destinationInput.value.trim() : "";
  if (!destVal) {
    setFieldError(destError, "Please enter a destination or click 'Suggest a Destination'.");
    isValid = false;
  } else if (destVal.length > 160) {
    setFieldError(destError, "Destination must not exceed 160 characters.");
    isValid = false;
  } else if (!isValidDestination(destVal)) {
    setFieldError(destError, "Destination may only contain letters, numbers, spaces, and punctuation characters.");
    isValid = false;
  }

  // 2. Duration Days
  const daysVal = durationInput ? parseInt(durationInput.value, 10) : NaN;
  if (isNaN(daysVal) || daysVal < 1 || daysVal > 30) {
    setFieldError(durationError, "Please enter a duration between 1 and 30 days.");
    isValid = false;
  }

  // 3. Budget Tier
  const selectedBudget = document.querySelector('input[name="budget"]:checked');
  if (!selectedBudget) {
    setFieldError(budgetError, "Please select a budget tier.");
    isValid = false;
  }

  return isValid;
}

// =====================================================================
// Staged Progress Indicator
// =====================================================================

function startLoading() {
  isSubmitting = true;
  if (generateBtn) {
    generateBtn.disabled = true;
    generateBtn.classList.add("btn-loading");
  }

  if (loadingContainer) {
    loadingContainer.hidden = false;
    loadingContainer.style.display = "block";
    loadingContainer.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  let stageIndex = 0;
  if (loadingStageText) {
    loadingStageText.textContent = STAGE_MESSAGES[0];
  }

  stageIntervalId = setInterval(() => {
    stageIndex = (stageIndex + 1) % STAGE_MESSAGES.length;
    if (loadingStageText) {
      loadingStageText.textContent = STAGE_MESSAGES[stageIndex];
    }
  }, 3500);
}

function stopLoading() {
  isSubmitting = false;
  if (generateBtn) {
    generateBtn.disabled = false;
    generateBtn.classList.remove("btn-loading");
  }

  if (stageIntervalId) {
    clearInterval(stageIntervalId);
    stageIntervalId = null;
  }

  if (loadingContainer) {
    loadingContainer.hidden = true;
    loadingContainer.style.display = "none";
  }
}

// =====================================================================
// Safe DOM Element Construction Helpers
// =====================================================================

function el(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== "") element.textContent = text;
  return element;
}

// =====================================================================
// Itinerary Rendering Engine (Full Width Layout)
// =====================================================================

/**
 * Render complete itinerary into the #itinerary-view container.
 *
 * @param {object} trip - The trip plan object returned by the server.
 * @param {boolean} [fromSavedTrips=false] - Whether viewed from saved trips catalog.
 */
function renderItinerary(trip, fromSavedTrips = false) {
  if (!itineraryView) return;

  // Clear previous itinerary
  while (itineraryView.firstChild) {
    itineraryView.removeChild(itineraryView.firstChild);
  }

  if (!trip || typeof trip !== "object") {
    itineraryView.hidden = true;
    itineraryView.style.display = "none";
    return;
  }

  const dest = trip.destination || "Custom Destination";
  const days = Number(trip.duration_days) || 1;
  const budgetTier = trip.budget || "Moderate";
  const interests = Array.isArray(trip.interests) ? trip.interests : [];
  const summary = trip.summary || "Your custom travel itinerary.";
  const currency = trip.estimated_budget?.currency || "USD";

  // 1. Header Card with Actions Bar
  const headerCard = el("div", "itinerary-header-card");

  const topBar = el("div", "itinerary-top-bar");
  topBar.appendChild(el("h2", "itinerary-destination", dest));

  const navActions = el("div", "itinerary-nav-actions");
  if (fromSavedTrips) {
    const btnBack = el("button", "btn btn-outline btn-sm", "← Back to Saved Trips");
    btnBack.type = "button";
    btnBack.addEventListener("click", () => switchView("saved-trips"));
    navActions.appendChild(btnBack);
  }
  const btnNewTrip = el("button", "btn btn-outline-teal btn-sm", "+ Plan Another Trip");
  btnNewTrip.type = "button";
  btnNewTrip.addEventListener("click", () => {
    if (destinationInput) destinationInput.value = "";
    if (itineraryView) {
      itineraryView.hidden = true;
      itineraryView.style.display = "none";
    }
    switchView("planner");
  });
  navActions.appendChild(btnNewTrip);
  topBar.appendChild(navActions);
  headerCard.appendChild(topBar);

  // Metadata Badges Row
  const badgesRow = el("div", "itinerary-badges-row");
  badgesRow.appendChild(el("span", "badge-pill bg-ocean-pill", `${days} Day${days > 1 ? "s" : ""}`));
  badgesRow.appendChild(el("span", "badge-pill bg-teal-pill", `${budgetTier} Tier`));
  if (trip.companions) {
    badgesRow.appendChild(el("span", "badge-pill bg-coral-pill", `${trip.companions} Travel`));
  }
  if (trip.climate && trip.climate !== "Any") {
    badgesRow.appendChild(el("span", "badge-pill bg-mint-pill", trip.climate));
  }
  interests.forEach((item) => {
    badgesRow.appendChild(el("span", "badge-pill bg-ocean-pill", item));
  });
  headerCard.appendChild(badgesRow);

  // Summary Narrative
  headerCard.appendChild(el("p", "itinerary-summary-text", summary));
  itineraryView.appendChild(headerCard);

  // 2. Experiences Section
  const experiences = Array.isArray(trip.experiences) ? trip.experiences : [];
  if (experiences.length > 0) {
    const expSection = el("section", "plan-section");
    expSection.appendChild(el("h3", "section-title", "Curated Experiences & Attractions"));
    const expGrid = el("div", "experiences-grid");

    experiences.forEach((exp) => {
      const card = el("div", "experience-card");
      const subHeader = el("div", "card-sub-header");
      subHeader.appendChild(el("h4", "experience-title", exp.name || "Attraction"));
      if (exp.estimated_cost) {
        subHeader.appendChild(el("span", "price-tag", exp.estimated_cost));
      }
      card.appendChild(subHeader);

      if (exp.category) {
        const catBadge = el("span", "badge-pill bg-ocean-pill", exp.category);
        catBadge.style.marginBottom = "0.5rem";
        card.appendChild(catBadge);
      }
      card.appendChild(el("p", "experience-desc", exp.description || ""));
      if (exp.practical_tip) {
        card.appendChild(el("p", "card-footer-tip", `Pro Tip: ${exp.practical_tip}`));
      }
      expGrid.appendChild(card);
    });
    expSection.appendChild(expGrid);
    itineraryView.appendChild(expSection);
  }

  // 3. Accommodations Section (2 Options)
  const accommodations = Array.isArray(trip.accommodations) ? trip.accommodations : [];
  if (accommodations.length > 0) {
    const accSection = el("section", "plan-section");
    accSection.appendChild(el("h3", "section-title", "Stay & Accommodation Options"));
    const accGrid = el("div", "accommodations-grid");

    accommodations.forEach((acc) => {
      const card = el("div", "accommodation-card");
      const subHeader = el("div", "card-sub-header");
      subHeader.appendChild(el("h4", "accommodation-title", acc.name || "Lodging Option"));
      const priceText = acc.nightly_price != null ? `~${acc.nightly_price} ${currency}/night` : "";
      if (priceText) {
        subHeader.appendChild(el("span", "price-tag", priceText));
      }
      card.appendChild(subHeader);

      if (acc.tier || acc.area) {
        const areaBadge = el("span", "badge-pill bg-teal-pill", `${acc.tier || "Option"} · ${acc.area || "Area"}`);
        areaBadge.style.marginBottom = "0.5rem";
        card.appendChild(areaBadge);
      }
      card.appendChild(el("p", "accommodation-reason", acc.reason || ""));
      if (acc.note) {
        card.appendChild(el("p", "card-footer-tip", `Note: ${acc.note}`));
      }
      accGrid.appendChild(card);
    });
    accSection.appendChild(accGrid);
    itineraryView.appendChild(accSection);
  }

  // 4. Ground Transit & Logistics Box
  const logistics = trip.logistics || {};
  const transitSection = el("section", "plan-section");
  transitSection.appendChild(el("h3", "section-title", "Transit & Ground Logistics"));
  const transitBox = el("div", "transit-box");

  if (logistics.overview) {
    transitBox.appendChild(el("p", "transit-overview", logistics.overview));
  }

  const transportOptions = Array.isArray(logistics.transport_options) ? logistics.transport_options : [];
  if (transportOptions.length > 0) {
    const optionsList = el("div", "transit-options-list");
    transportOptions.forEach((opt) => {
      const item = el("div", "transit-option-item");
      item.appendChild(el("h4", "transit-mode", opt.mode || "Transit"));
      if (opt.approx_cost_per_trip != null) {
        item.appendChild(el("p", "transit-cost", `Approx: ${opt.approx_cost_per_trip} ${currency} / trip`));
      }
      item.appendChild(el("p", "transit-notes", opt.description || opt.notes || ""));
      optionsList.appendChild(item);
    });
    transitBox.appendChild(optionsList);
  }

  const detailsGrid = el("div", "logistics-details-grid");
  const tips = Array.isArray(logistics.tips) ? logistics.tips : [];
  if (tips.length > 0) {
    const tipBlock = el("div", "detail-block");
    tipBlock.appendChild(el("h4", "", "Transit Tips"));
    const ul = el("ul", "");
    tips.forEach((t) => ul.appendChild(el("li", "", t)));
    tipBlock.appendChild(ul);
    detailsGrid.appendChild(tipBlock);
  }

  const safety = Array.isArray(logistics.safety) ? logistics.safety : [];
  if (safety.length > 0) {
    const safeBlock = el("div", "detail-block");
    safeBlock.appendChild(el("h4", "", "Safety Guidance"));
    const ul = el("ul", "");
    safety.forEach((s) => ul.appendChild(el("li", "", s)));
    safeBlock.appendChild(ul);
    detailsGrid.appendChild(safeBlock);
  }

  const verify = Array.isArray(logistics.verify) ? logistics.verify : [];
  if (verify.length > 0) {
    const verBlock = el("div", "detail-block");
    verBlock.appendChild(el("h4", "", "Verify Before Travel"));
    const ul = el("ul", "");
    verify.forEach((v) => ul.appendChild(el("li", "", v)));
    verBlock.appendChild(ul);
    detailsGrid.appendChild(verBlock);
  }

  if (detailsGrid.children.length > 0) {
    transitBox.appendChild(detailsGrid);
  }
  transitSection.appendChild(transitBox);
  itineraryView.appendChild(transitSection);

  // 5. Day-by-Day Itinerary Schedule
  const itineraryDays = Array.isArray(trip.itinerary) ? trip.itinerary : [];
  if (itineraryDays.length > 0) {
    const itinSection = el("section", "plan-section");
    itinSection.appendChild(el("h3", "section-title", "Day-by-Day Master Schedule"));

    itineraryDays.forEach((dayData) => {
      const dayCard = el("div", "day-card");
      const dHeader = el("div", "day-header");
      dHeader.appendChild(el("span", "day-number-tag", `Day ${dayData.day || 1}`));
      dHeader.appendChild(el("h4", "day-title", dayData.title || "Daily Exploration"));
      dayCard.appendChild(dHeader);

      const segments = el("div", "day-segments");
      ["morning", "afternoon", "evening"].forEach((timeSlot) => {
        const slotItems = Array.isArray(dayData[timeSlot]) ? dayData[timeSlot] : [];
        if (slotItems.length > 0) {
          const seg = el("div", "day-segment");
          seg.appendChild(el("span", "segment-label", timeSlot));
          const ul = el("ul", "segment-items");
          slotItems.forEach((activity) => ul.appendChild(el("li", "", activity)));
          seg.appendChild(ul);
          segments.appendChild(seg);
        }
      });
      dayCard.appendChild(segments);
      itinSection.appendChild(dayCard);
    });
    itineraryView.appendChild(itinSection);
  }

  // 6. Mathematical Budget Breakdown Table
  const budget = trip.estimated_budget;
  if (budget && typeof budget === "object") {
    const budgetSection = el("section", "plan-section");
    budgetSection.appendChild(el("h3", "section-title", "Estimated Travel Budget"));

    const bCard = el("div", "budget-card");
    const table = el("table", "budget-table");
    const thead = el("thead");
    const trH = el("tr");
    trH.appendChild(el("th", "", "Category"));
    trH.appendChild(el("th", "", "Rate"));
    trH.appendChild(el("th", "", "Subtotal"));
    thead.appendChild(trH);
    table.appendChild(thead);

    const tbody = el("tbody");
    const nights = budget.nights ?? Math.max(days - 1, 0);

    const addRow = (cat, rate, sub) => {
      const tr = el("tr");
      tr.appendChild(el("td", "", cat));
      tr.appendChild(el("td", "", rate));
      tr.appendChild(el("td", "", sub));
      tbody.appendChild(tr);
    };

    addRow("Lodging", `${budget.accommodation_per_night ?? 0} ${currency} × ${nights} nights`, `${budget.accommodation ?? 0} ${currency}`);
    addRow("Food & Dining", `${budget.food_per_day ?? 0} ${currency}/day × ${days} days`, `${budget.food ?? 0} ${currency}`);
    addRow("Local Transit", `${budget.transport_per_day ?? 0} ${currency}/day × ${days} days`, `${budget.transport ?? 0} ${currency}`);
    addRow("Activities & Tours", "Total Estimates", `${budget.activities ?? 0} ${currency}`);

    const trTot = el("tr", "budget-total-row");
    trTot.appendChild(el("td", "", "Total Estimated Cost"));
    trTot.appendChild(el("td", "", "(Flights Excluded)"));
    trTot.appendChild(el("td", "total-amount", `${budget.total ?? 0} ${currency}`));
    tbody.appendChild(trTot);
    table.appendChild(tbody);
    bCard.appendChild(table);

    // Disclaimers
    const discBox = el("div", "plan-disclaimers-box");
    discBox.appendChild(el("h4", "disclaimer-title", "Planning Notice & Math Accuracy"));
    discBox.appendChild(
      el(
        "p",
        "disclaimer-text",
        "Cost totals are computed deterministically in Python (accommodation + food + transit + activities). Estimates are illustrative and unverified. Verify real-time availability and flight pricing independently."
      )
    );
    bCard.appendChild(discBox);
    budgetSection.appendChild(bCard);
    itineraryView.appendChild(budgetSection);
  }

  // Reveal itinerary view and scroll smoothly into view
  itineraryView.hidden = false;
  itineraryView.style.display = "flex";
  itineraryView.scrollIntoView({ behavior: "smooth", block: "start" });
}

// =====================================================================
// Saved Trips Catalog Management
// =====================================================================

function getDestinationImage(destName) {
  if (!destName) return null;
  const lower = destName.toLowerCase();
  for (const [key, url] of Object.entries(DESTINATION_IMAGES)) {
    if (lower.includes(key)) {
      return url;
    }
  }
  return null;
}

function formatDate(isoString) {
  if (!isoString) return "";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return "";
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

function updateTripsCountBadges(count) {
  const countStr = String(count);
  if (sidebarTripsCount) sidebarTripsCount.textContent = countStr;
  if (dashboardTripsCount) dashboardTripsCount.textContent = countStr;
  if (savedTripsBadge) savedTripsBadge.textContent = countStr;
}

function renderSavedTripsGrid(trips) {
  if (!savedTripsGrid || !savedTripsEmpty) return;

  while (savedTripsGrid.firstChild) {
    savedTripsGrid.removeChild(savedTripsGrid.firstChild);
  }

  const list = Array.isArray(trips) ? trips : [];

  if (list.length === 0) {
    savedTripsGrid.style.display = "none";
    savedTripsEmpty.hidden = false;
    savedTripsEmpty.style.display = "block";
    return;
  }

  savedTripsEmpty.hidden = true;
  savedTripsEmpty.style.display = "none";
  savedTripsGrid.style.display = "grid";

  list.forEach((item) => {
    const card = el("div", "saved-card");

    // Banner Image / Gradient Fallback
    const banner = el("div", "saved-card-banner");
    const imgUrl = getDestinationImage(item.destination);

    if (imgUrl) {
      const img = el("img", "saved-card-img");
      img.src = imgUrl;
      img.alt = item.destination || "Destination";
      img.onerror = () => {
        banner.classList.add("img-failed");
        img.style.display = "none";
      };
      banner.appendChild(img);
    } else {
      banner.classList.add("img-failed");
    }

    const gradient = el("div", "saved-card-gradient bg-gradient-default");
    gradient.textContent = "✈️";
    banner.appendChild(gradient);

    // Total Cost Pill on Banner
    const totalCost = item.estimated_budget?.total;
    const currency = item.estimated_budget?.currency || "";
    if (totalCost != null) {
      banner.appendChild(el("span", "saved-card-cost-pill", `${totalCost} ${currency}`));
    }
    card.appendChild(banner);

    // Card Body
    const body = el("div", "saved-card-body");
    body.appendChild(el("h3", "saved-card-dest", item.destination || "Custom Trip"));

    // Tags
    const tags = el("div", "saved-card-tags");
    tags.appendChild(el("span", "badge-pill bg-ocean-pill", `${item.duration_days || 1} Days`));
    tags.appendChild(el("span", "badge-pill bg-teal-pill", `${item.budget || "Moderate"}`));
    if (item.companions) {
      tags.appendChild(el("span", "badge-pill bg-coral-pill", item.companions));
    }
    body.appendChild(tags);

    // Created Date
    const dStr = formatDate(item.created_at);
    if (dStr) {
      body.appendChild(el("p", "saved-card-date", `Created on ${dStr}`));
    }

    // Actions: View Plan & Delete
    const actions = el("div", "saved-card-actions");
    const btnView = el("button", "btn btn-primary btn-sm", "View Plan");
    btnView.type = "button";
    btnView.addEventListener("click", () => {
      renderItinerary(item, true);
      switchView("planner");
    });
    actions.appendChild(btnView);

    const btnDelete = el("button", "btn btn-outline-danger btn-sm btn-delete", "🗑️");
    btnDelete.type = "button";
    btnDelete.title = `Delete trip to ${item.destination}`;
    btnDelete.setAttribute("aria-label", `Delete trip to ${item.destination}`);
    btnDelete.addEventListener("click", () => openDeleteConfirm(item));
    actions.appendChild(btnDelete);

    body.appendChild(actions);
    card.appendChild(body);
    savedTripsGrid.appendChild(card);
  });
}

function filterAndDisplaySavedTrips() {
  const searchTerm = (savedTripsSearch?.value || "").trim().toLowerCase();
  const budgetTier = filterBudget?.value || "";
  const durationChoice = filterDuration?.value || "";

  let filtered = currentSavedTrips.filter((item) => {
    // 1. Search Query
    if (searchTerm) {
      const dest = (item.destination || "").toLowerCase();
      const summary = (item.summary || "").toLowerCase();
      if (!dest.includes(searchTerm) && !summary.includes(searchTerm)) {
        return false;
      }
    }

    // 2. Budget Tier
    if (budgetTier && item.budget !== budgetTier) {
      return false;
    }

    // 3. Duration Choice
    const days = Number(item.duration_days) || 1;
    if (durationChoice === "short" && days > 3) return false;
    if (durationChoice === "medium" && (days < 4 || days > 7)) return false;
    if (durationChoice === "long" && days < 8) return false;

    return true;
  });

  renderSavedTripsGrid(filtered);
}

async function loadSavedTrips() {
  try {
    const response = await apiRequest("/api/trips");
    if (response && response.ok && Array.isArray(response.trips)) {
      currentSavedTrips = response.trips;
      updateTripsCountBadges(currentSavedTrips.length);
      filterAndDisplaySavedTrips();
    }
  } catch (err) {
    console.warn("Could not load saved trips:", err.message);
  }
}

// =====================================================================
// Delete Confirmation Modal Handling
// =====================================================================

function openDeleteConfirm(trip) {
  if (!deleteDialog) return;
  pendingDeleteTripId = trip.trip_id;
  if (deleteDestName) {
    deleteDestName.textContent = trip.destination || "this trip";
  }
  if (typeof deleteDialog.showModal === "function") {
    deleteDialog.showModal();
  } else {
    deleteDialog.setAttribute("open", "");
  }
}

function closeDeleteConfirm() {
  if (!deleteDialog) return;
  pendingDeleteTripId = null;
  if (typeof deleteDialog.close === "function") {
    deleteDialog.close();
  } else {
    deleteDialog.removeAttribute("open");
  }
}

async function executeTripDeletion() {
  if (!pendingDeleteTripId) return;
  const tripIdToDelete = pendingDeleteTripId;
  closeDeleteConfirm();

  try {
    const resp = await apiRequest(`/api/trips/${encodeURIComponent(tripIdToDelete)}`, {
      method: "DELETE",
    });

    if (resp && resp.ok) {
      currentSavedTrips = currentSavedTrips.filter((t) => t.trip_id !== tripIdToDelete);
      updateTripsCountBadges(currentSavedTrips.length);
      filterAndDisplaySavedTrips();
      showToast("Trip removed from saved itineraries.", "info");

      // If this trip was currently displayed in itinerary view, close it
      if (itineraryView && !itineraryView.hidden) {
        itineraryView.hidden = true;
        itineraryView.style.display = "none";
      }
    } else {
      showToast("Failed to delete trip. Please try again.", "danger");
    }
  } catch (err) {
    showToast(`Error deleting trip: ${err.message}`, "danger");
  }
}

// =====================================================================
// Form Submission & Planning Pipeline
// =====================================================================

async function handleFormSubmit(event) {
  event.preventDefault();
  if (isSubmitting) return;

  hideErrorBanner();
  if (!validatePlannerForm()) return;

  const destVal = destinationInput.value.trim();
  const daysVal = parseInt(durationInput.value, 10);
  const budgetVal = document.querySelector('input[name="budget"]:checked').value;
  const companionsVal = companionsSelect ? companionsSelect.value : "Solo";
  const climateVal = climateSelect ? climateSelect.value : "Any";

  const selectedInterests = Array.from(
    document.querySelectorAll('input[name="interests"]:checked')
  ).map((cb) => cb.value);

  const placeIdInput = document.getElementById("selected-place-id");
  const locCtxInput = document.getElementById("selected-location-context");
  const placeId = placeIdInput ? placeIdInput.value.trim() : "";
  const locationContext = locCtxInput ? locCtxInput.value.trim() : "";

  const payload = {
    destination: destVal,
    duration_days: daysVal,
    budget: budgetVal,
    interests: selectedInterests,
    companions: companionsVal,
    climate: climateVal,
  };
  if (placeId) payload.place_id = placeId;
  if (locationContext) payload.location_context = locationContext;
  if (selectedAttractions && selectedAttractions.length > 0) {
    payload.selected_attractions = selectedAttractions;
  }

  startLoading();

  try {
    const response = await apiRequest("/api/plan", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (response && response.ok && response.trip) {
      renderItinerary(response.trip, false);
      showToast(`Itinerary for ${response.trip.destination} ready & saved!`, "success");
      // Refresh saved trips in background
      await loadSavedTrips();
    } else {
      throw new Error("Server returned an incomplete trip response.");
    }
  } catch (err) {
    if (err.field === "destination") {
      setFieldError(destError, err.message);
    } else if (err.field === "duration_days") {
      setFieldError(durationError, err.message);
    } else if (err.field === "budget") {
      setFieldError(budgetError, err.message);
    } else if (err.field === "interests") {
      setFieldError(interestsError, err.message);
    } else {
      showErrorBanner(err.message);
      showToast(err.message, "danger");
    }
  } finally {
    stopLoading();
  }
}

// =====================================================================
// Event Listeners & Application Initialization
// =====================================================================

document.addEventListener("DOMContentLoaded", () => {
  // Ensure error banner is closed on start
  hideErrorBanner();

  // Restore sidebar collapse state from localStorage
  try {
    const savedCollapse = localStorage.getItem("voyage_sidebar_collapsed");
    if (savedCollapse === "1") {
      document.body.classList.add("sidebar-collapsed");
    }
  } catch {
    // Ignore storage issues
  }

  // 1. Sidebar Collapse Toggle
  if (sidebarCollapseBtn) {
    sidebarCollapseBtn.addEventListener("click", toggleSidebarCollapse);
  }

  // 2. Mobile Drawer Controls
  if (mobileMenuToggle) {
    mobileMenuToggle.addEventListener("click", openMobileDrawer);
  }
  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener("click", closeMobileDrawer);
  }
  if (mobileQuickPlan) {
    mobileQuickPlan.addEventListener("click", () => switchView("planner"));
  }

  // 3. Navigation View Switching
  if (navDashboard) {
    navDashboard.addEventListener("click", () => switchView("dashboard"));
  }
  if (navExplore) {
    navExplore.addEventListener("click", () => switchView("explore"));
  }
  if (navPlanner) {
    navPlanner.addEventListener("click", () => switchView("planner"));
  }
  if (navSavedTrips) {
    navSavedTrips.addEventListener("click", () => switchView("saved-trips"));
  }

  // Brand Logo Click -> Dashboard
  const brandLogoLink = document.getElementById("brand-logo-link");
  if (brandLogoLink) {
    brandLogoLink.addEventListener("click", (e) => {
      e.preventDefault();
      switchView("dashboard");
    });
  }

  // 4. Hero & Dashboard Actions
  if (btnHeroPlan) {
    btnHeroPlan.addEventListener("click", () => switchView("planner"));
  }
  if (btnHeroExplore) {
    btnHeroExplore.addEventListener("click", () => switchView("explore"));
  }
  if (btnHeroSaved) {
    btnHeroSaved.addEventListener("click", () => switchView("saved-trips"));
  }

  // Quick Inspiration Destination Buttons
  document.querySelectorAll(".btn-quick-dest").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dest = btn.getAttribute("data-dest");
      const days = btn.getAttribute("data-days");
      const budget = btn.getAttribute("data-budget");

      if (destinationInput && dest) destinationInput.value = dest;
      if (durationInput && days) durationInput.value = days;
      if (budget) {
        const radio = document.querySelector(`input[name="budget"][value="${budget}"]`);
        if (radio) radio.checked = true;
      }
      switchView("planner");
      if (destinationInput) destinationInput.focus();
    });
  });

  // 5. Planner Form Listeners
  if (plannerForm) {
    plannerForm.addEventListener("submit", handleFormSubmit);
  }

  // Quick Duration Chips
  quickDayChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      quickDayChips.forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      const days = chip.getAttribute("data-days");
      if (durationInput && days) {
        durationInput.value = days;
        if (durationError) {
          durationError.textContent = "";
          durationError.classList.remove("active");
        }
      }
    });
  });

  // Suggest a Destination Button
  if (suggestDestBtn) {
    suggestDestBtn.addEventListener("click", async () => {
      const daysVal = durationInput ? parseInt(durationInput.value, 10) || 3 : 3;
      const budgetRadio = document.querySelector('input[name="budget"]:checked');
      const budgetVal = budgetRadio ? budgetRadio.value : "Moderate";
      const companionsVal = companionsSelect ? companionsSelect.value : "Solo";
      const climateVal = climateSelect ? climateSelect.value : "Any";

      const selectedInterests = Array.from(
        document.querySelectorAll('input[name="interests"]:checked')
      ).map((cb) => cb.value);

      suggestDestBtn.disabled = true;
      const originalText = suggestDestBtn.textContent;
      suggestDestBtn.textContent = "Matching...";

      try {
        const resp = await apiRequest("/api/recommend-destination", {
          method: "POST",
          body: JSON.stringify({
            budget: budgetVal,
            duration_days: daysVal,
            interests: selectedInterests,
            companions: companionsVal,
            climate: climateVal,
          }),
        });

        if (resp && resp.ok && Array.isArray(resp.recommendations) && resp.recommendations.length > 0) {
          const top = resp.recommendations[0];
          if (destinationInput) {
            destinationInput.value = top.destination;
            if (destError) {
              destError.textContent = "";
              destError.classList.remove("active");
            }
            destinationInput.focus();
            showToast(`Suggested: ${top.destination} (${top.match_score}% match)`, "success");
          }
        } else {
          showToast("No destination matches found. Try selecting different interests.", "info");
        }
      } catch (err) {
        console.warn("Destination recommendation failed:", err.message);
        showToast("Could not fetch suggestion. Enter any destination directly.", "info");
      } finally {
        suggestDestBtn.disabled = false;
        suggestDestBtn.textContent = originalText;
      }
    });
  }

  // ===================================================================
  // Selected Attractions State & Management
  // ===================================================================
  let selectedAttractions = [];

  function addSelectedAttraction(item) {
    if (!item || !item.name) return;
    const exists = selectedAttractions.some(
      (a) => (a.id && item.id && a.id === item.id) || a.name.toLowerCase() === item.name.toLowerCase()
    );
    if (!exists) {
      selectedAttractions.push({
        id: item.id || item.name.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
        name: item.name,
        city: item.city || "",
        country: item.country || "",
        category: item.category || "General",
        description: item.description || "",
      });
      renderSelectedAttractionsChips();
      updateQueueBanner();
      updateExploreSelectionStates();
    }
  }

  function removeSelectedAttraction(targetIdOrName) {
    selectedAttractions = selectedAttractions.filter(
      (a) => a.id !== targetIdOrName && a.name !== targetIdOrName
    );
    renderSelectedAttractionsChips();
    updateQueueBanner();
    updateExploreSelectionStates();
  }

  function clearSelectedAttractions() {
    selectedAttractions = [];
    renderSelectedAttractionsChips();
    updateQueueBanner();
    updateExploreSelectionStates();
  }

  function renderSelectedAttractionsChips() {
    if (!selectedAttractionsContainer) return;
    selectedAttractionsContainer.innerHTML = "";

    if (selectedAttractions.length === 0) {
      if (noAttractionsHint) {
        noAttractionsHint.classList.remove("hidden");
        selectedAttractionsContainer.appendChild(noAttractionsHint);
      }
      return;
    }

    selectedAttractions.forEach((att) => {
      const chip = document.createElement("div");
      chip.className = "attraction-chip";

      const nameSpan = document.createElement("span");
      nameSpan.className = "chip-name";
      nameSpan.textContent = att.name;
      chip.appendChild(nameSpan);

      if (att.category) {
        const catSpan = document.createElement("span");
        catSpan.className = "chip-category";
        catSpan.textContent = att.category;
        chip.appendChild(catSpan);
      }

      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "chip-remove-btn";
      removeBtn.setAttribute("aria-label", `Remove ${att.name}`);
      removeBtn.innerHTML = "&times;";
      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        removeSelectedAttraction(att.id || att.name);
      });
      chip.appendChild(removeBtn);

      selectedAttractionsContainer.appendChild(chip);
    });
  }

  function updateQueueBanner() {
    const count = selectedAttractions.length;
    const exploreSelectedCount = document.getElementById("explore-selected-count");
    if (exploreSelectedCount) exploreSelectedCount.textContent = count;
    if (queueCount) queueCount.textContent = count;

    if (!exploreSelectedBanner) return;
    if (count === 0) {
      exploreSelectedBanner.classList.add("hidden");
    } else {
      exploreSelectedBanner.classList.remove("hidden");
      if (queueItemsPreview) {
        queueItemsPreview.textContent = selectedAttractions.map((a) => a.name).join(", ");
      }
    }
  }

  function updateExploreSelectionStates() {
    if (!exploreGrid) return;
    const cards = exploreGrid.querySelectorAll(".attraction-card");
    const selectedIds = new Set(selectedAttractions.map((a) => a.id));
    const selectedNames = new Set(selectedAttractions.map((a) => a.name.toLowerCase()));

    cards.forEach((card) => {
      const cId = card.getAttribute("data-id");
      const cName = (card.getAttribute("data-name") || "").toLowerCase();
      const isSelected = selectedIds.has(cId) || selectedNames.has(cName);
      card.classList.toggle("is-selected", isSelected);

      const addBtn = card.querySelector(".btn-add-attraction");
      if (addBtn) {
        if (isSelected) {
          addBtn.classList.add("btn-added");
          addBtn.textContent = "✓ In Trip Plan";
        } else {
          addBtn.classList.remove("btn-added");
          addBtn.textContent = "+ Add to Trip";
        }
      }
    });
  }

  // ===================================================================
  // Explore Destinations & Worldwide Discovery Engine
  // ===================================================================
  let exploreDebounceTimer = null;
  let exploreFacetsLoaded = false;
  let exploreState = {
    query: "",
    continent: "",
    country: "",
    category: "",
    budget: "",
    traveler_type: "",
  };

  async function loadExploreFacets() {
    if (exploreFacetsLoaded) return;
    try {
      const res = await apiRequest("/api/destinations/facets");
      if (res && res.ok && res.facets) {
        exploreFacetsLoaded = true;
        if (sidebarAttractionsCount && res.facets.total_attractions) {
          sidebarAttractionsCount.textContent = res.facets.total_attractions;
        }
        if (exploreFilterCountry && res.facets.countries) {
          exploreFilterCountry.innerHTML = '<option value="">All Countries</option>';
          res.facets.countries.forEach((c) => {
            const opt = document.createElement("option");
            opt.value = c.name;
            opt.textContent = `${c.name} (${c.count})`;
            exploreFilterCountry.appendChild(opt);
          });
        }
      }
    } catch (err) {
      console.warn("Could not load destination facets:", err);
    }
  }

  async function loadExploreAttractions() {
    await loadExploreFacets();
    await fetchAndRenderAttractions();
  }

  async function fetchAndRenderAttractions() {
    if (!exploreGrid) return;
    exploreGrid.innerHTML = '<div class="explore-loading"><div class="spinner-coral"></div><p>Searching worldwide database...</p></div>';
    if (exploreEmptyState) exploreEmptyState.classList.add("hidden");

    const params = new URLSearchParams();
    if (exploreState.query) params.set("query", exploreState.query);
    if (exploreState.continent) params.set("continent", exploreState.continent);
    if (exploreState.country) params.set("country", exploreState.country);
    if (exploreState.category) params.set("category", exploreState.category);
    if (exploreState.budget) params.set("budget", exploreState.budget);
    if (exploreState.traveler_type) params.set("traveler_type", exploreState.traveler_type);
    params.set("limit", "100");

    try {
      const res = await apiRequest(`/api/destinations/search?${params.toString()}`);
      if (res && res.ok) {
        renderAttractionsGrid(res.attractions || []);
        if (exploreResultsCount) {
          exploreResultsCount.textContent = res.total || 0;
        }
      } else {
        renderAttractionsGrid([]);
      }
    } catch (err) {
      console.warn("Failed to fetch attractions:", err);
      renderAttractionsGrid([]);
    }
  }

  function renderAttractionsGrid(attractions) {
    if (!exploreGrid) return;
    exploreGrid.innerHTML = "";

    if (!attractions || attractions.length === 0) {
      exploreGrid.classList.add("hidden");
      if (exploreEmptyState) exploreEmptyState.classList.remove("hidden");
      return;
    }

    exploreGrid.classList.remove("hidden");
    if (exploreEmptyState) exploreEmptyState.classList.add("hidden");

    const selectedIds = new Set(selectedAttractions.map((a) => a.id));
    const selectedNames = new Set(selectedAttractions.map((a) => a.name.toLowerCase()));

    attractions.forEach((item) => {
      const isSelected = selectedIds.has(item.id) || selectedNames.has(item.name.toLowerCase());

      const card = document.createElement("div");
      card.className = "attraction-card";
      if (isSelected) card.classList.add("is-selected");
      card.setAttribute("data-id", item.id || "");
      card.setAttribute("data-name", item.name || "");

      // Card Header / Banner
      const cardHeader = document.createElement("div");
      cardHeader.className = "attraction-card-header";

      const badgesRow = document.createElement("div");
      badgesRow.className = "attraction-badges-row";

      const catBadge = document.createElement("span");
      catBadge.className = `badge-pill cat-${(item.category || "general").toLowerCase()}`;
      catBadge.textContent = item.category || "Sight";
      badgesRow.appendChild(catBadge);

      const contBadge = document.createElement("span");
      contBadge.className = "badge-pill bg-continent";
      contBadge.textContent = `${item.continent} • ${item.country}`;
      badgesRow.appendChild(contBadge);

      cardHeader.appendChild(badgesRow);
      card.appendChild(cardHeader);

      // Card Body
      const cardBody = document.createElement("div");
      cardBody.className = "attraction-card-body";

      const title = document.createElement("h3");
      title.className = "attraction-title";
      title.textContent = item.name;
      cardBody.appendChild(title);

      const locationEl = document.createElement("div");
      locationEl.className = "attraction-location";
      locationEl.innerHTML = `📍 ${item.city ? item.city + ', ' : ''}${item.country}`;
      cardBody.appendChild(locationEl);

      const desc = document.createElement("p");
      desc.className = "attraction-description";
      desc.textContent = item.description || "";
      cardBody.appendChild(desc);

      // Meta list
      const metaList = document.createElement("div");
      metaList.className = "attraction-meta-grid";

      if (item.duration_hours) {
        const metaItem = document.createElement("span");
        metaItem.className = "meta-pill";
        metaItem.innerHTML = `⏱ ${item.duration_hours}`;
        metaList.appendChild(metaItem);
      }
      if (item.best_season) {
        const metaItem = document.createElement("span");
        metaItem.className = "meta-pill";
        metaItem.innerHTML = `☀️ ${item.best_season}`;
        metaList.appendChild(metaItem);
      }
      if (item.budget_tier) {
        const metaItem = document.createElement("span");
        metaItem.className = "meta-pill";
        metaItem.innerHTML = `💰 ${item.budget_tier}${item.estimated_cost ? ' (' + item.estimated_cost + ')' : ''}`;
        metaList.appendChild(metaItem);
      }
      cardBody.appendChild(metaList);

      // Tags
      if (item.tags && item.tags.length > 0) {
        const tagsRow = document.createElement("div");
        tagsRow.className = "attraction-tags-row";
        item.tags.slice(0, 5).forEach((t) => {
          const tagSpan = document.createElement("span");
          tagSpan.className = "tag-mini";
          tagSpan.textContent = `#${t}`;
          tagsRow.appendChild(tagSpan);
        });
        cardBody.appendChild(tagsRow);
      }

      card.appendChild(cardBody);

      // Card Actions
      const cardActions = document.createElement("div");
      cardActions.className = "attraction-card-actions";

      const addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "btn btn-sm btn-outline-coral btn-add-attraction";
      if (isSelected) {
        addBtn.classList.add("btn-added");
        addBtn.textContent = "✓ In Trip Plan";
      } else {
        addBtn.textContent = "+ Add to Trip";
      }
      addBtn.addEventListener("click", () => {
        const currentlySelected = selectedAttractions.some(
          (a) => (a.id && a.id === item.id) || a.name.toLowerCase() === item.name.toLowerCase()
        );
        if (currentlySelected) {
          removeSelectedAttraction(item.id || item.name);
          showToast(`Removed "${item.name}" from selected attractions.`, "info");
        } else {
          addSelectedAttraction(item);
          showToast(`Added "${item.name}" to your trip highlights!`, "success");
        }
      });
      cardActions.appendChild(addBtn);

      const planHereBtn = document.createElement("button");
      planHereBtn.type = "button";
      planHereBtn.className = "btn btn-sm btn-coral btn-plan-here";
      planHereBtn.textContent = "Plan Trip Here";
      planHereBtn.addEventListener("click", () => {
        if (destinationInput) {
          destinationInput.value = `${item.city || item.name}, ${item.country}`;
        }
        addSelectedAttraction(item);
        switchView("planner");
        showToast(`Destination set to ${item.city || item.name}, ${item.country}!`, "success");
      });
      cardActions.appendChild(planHereBtn);

      card.appendChild(cardActions);
      exploreGrid.appendChild(card);
    });
  }

  // Explore Event Listeners
  if (exploreSearchInput) {
    exploreSearchInput.addEventListener("input", (e) => {
      exploreState.query = e.target.value.trim();
      if (exploreClearSearch) {
        exploreClearSearch.classList.toggle("hidden", !exploreState.query);
      }
      clearTimeout(exploreDebounceTimer);
      exploreDebounceTimer = setTimeout(() => {
        fetchAndRenderAttractions();
      }, 250);
    });
  }

  if (exploreClearSearch) {
    exploreClearSearch.addEventListener("click", () => {
      if (exploreSearchInput) exploreSearchInput.value = "";
      exploreState.query = "";
      exploreClearSearch.classList.add("hidden");
      fetchAndRenderAttractions();
    });
  }

  // Continent Filter Pills
  const continentPills = document.querySelectorAll(".continent-pill");
  continentPills.forEach((pill) => {
    pill.addEventListener("click", () => {
      continentPills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      exploreState.continent = pill.getAttribute("data-continent") || "";
      fetchAndRenderAttractions();
    });
  });

  if (exploreFilterCountry) {
    exploreFilterCountry.addEventListener("change", (e) => {
      exploreState.country = e.target.value;
      fetchAndRenderAttractions();
    });
  }
  if (exploreFilterCategory) {
    exploreFilterCategory.addEventListener("change", (e) => {
      exploreState.category = e.target.value;
      fetchAndRenderAttractions();
    });
  }
  if (exploreFilterBudget) {
    exploreFilterBudget.addEventListener("change", (e) => {
      exploreState.budget = e.target.value;
      fetchAndRenderAttractions();
    });
  }
  if (exploreFilterTraveler) {
    exploreFilterTraveler.addEventListener("change", (e) => {
      exploreState.traveler_type = e.target.value;
      fetchAndRenderAttractions();
    });
  }

  function resetExploreFilters() {
    exploreState = {
      query: "",
      continent: "",
      country: "",
      category: "",
      budget: "",
      traveler_type: "",
    };
    if (exploreSearchInput) exploreSearchInput.value = "";
    if (exploreClearSearch) exploreClearSearch.classList.add("hidden");
    if (exploreFilterCountry) exploreFilterCountry.value = "";
    if (exploreFilterCategory) exploreFilterCategory.value = "";
    if (exploreFilterBudget) exploreFilterBudget.value = "";
    if (exploreFilterTraveler) exploreFilterTraveler.value = "";
    continentPills.forEach((p) => {
      p.classList.toggle("active", !p.getAttribute("data-continent"));
    });
    fetchAndRenderAttractions();
  }

  if (btnExploreResetFilters) {
    btnExploreResetFilters.addEventListener("click", resetExploreFilters);
  }
  if (btnExploreResetEmpty) {
    btnExploreResetEmpty.addEventListener("click", resetExploreFilters);
  }
  if (btnExploreToPlanner) {
    btnExploreToPlanner.addEventListener("click", () => switchView("planner"));
  }
  if (btnApplySelectedToPlan) {
    btnApplySelectedToPlan.addEventListener("click", () => switchView("planner"));
  }
  if (btnClearSelectedAttractions) {
    btnClearSelectedAttractions.addEventListener("click", () => {
      clearSelectedAttractions();
      showToast("Cleared selected attractions.", "info");
    });
  }
  if (btnBrowseCatalogLink) {
    btnBrowseCatalogLink.addEventListener("click", () => switchView("explore"));
  }

  // ===================================================================
  // Fast Local Destination & Attraction Autocomplete
  // ===================================================================
  let autocompleteDebounceTimer = null;
  let currentAutocompleteIndex = -1;

  function closeAutocompleteDropdown() {
    const dropdown = document.getElementById("destination-autocomplete-dropdown");
    if (dropdown) {
      dropdown.innerHTML = "";
      dropdown.classList.add("hidden");
      if (destinationInput) destinationInput.setAttribute("aria-expanded", "false");
    }
    currentAutocompleteIndex = -1;
  }

  function selectAutocompleteItem(item) {
    if (!item || !destinationInput) return;

    if (item.type === "attraction") {
      destinationInput.value = item.city && item.country ? `${item.city}, ${item.country}` : item.name;
      addSelectedAttraction({
        id: item.id,
        name: item.name,
        city: item.city,
        country: item.country,
        category: item.category,
      });
      showToast(`Added "${item.name}" to your trip highlights!`, "success");
    } else {
      destinationInput.value = item.display || item.name;
    }

    const placeIdInput = document.getElementById("selected-place-id");
    const locCtxInput = document.getElementById("selected-location-context");
    if (placeIdInput) placeIdInput.value = item.id || "";
    if (locCtxInput) locCtxInput.value = item.country || "";

    closeAutocompleteDropdown();

    if (destError) {
      destError.textContent = "";
      destError.classList.remove("active");
    }
  }

  function renderAutocompleteSuggestions(data) {
    const dropdown = document.getElementById("destination-autocomplete-dropdown");
    if (!dropdown) return;
    dropdown.innerHTML = "";

    const suggestions = data && data.suggestions ? data.suggestions : [];
    if (!suggestions.length) {
      closeAutocompleteDropdown();
      return;
    }

    suggestions.forEach((item, idx) => {
      const itemEl = document.createElement("div");
      itemEl.className = "autocomplete-item";
      itemEl.setAttribute("role", "option");
      itemEl.setAttribute("id", `ac-opt-${idx}`);
      itemEl.setAttribute("data-index", idx);

      const mainWrap = document.createElement("div");
      mainWrap.className = "autocomplete-item-main";

      const titleEl = document.createElement("span");
      titleEl.className = "autocomplete-item-title";
      titleEl.textContent = item.name || item.display;
      mainWrap.appendChild(titleEl);

      const secText = item.city && item.country ? `${item.city}, ${item.country}` : (item.display || "");
      if (secText && secText !== item.name) {
        const secEl = document.createElement("span");
        secEl.className = "autocomplete-item-secondary";
        secEl.textContent = secText;
        mainWrap.appendChild(secEl);
      }
      itemEl.appendChild(mainWrap);

      if (item.category) {
        const badge = document.createElement("span");
        badge.className = "autocomplete-badge";
        const catLower = item.category.toLowerCase();
        if (catLower.includes("nature")) badge.classList.add("badge-park");
        else if (catLower.includes("beach")) badge.classList.add("badge-island");
        else if (catLower.includes("historical")) badge.classList.add("badge-landmark");
        badge.textContent = item.category;
        itemEl.appendChild(badge);
      }

      itemEl.addEventListener("click", () => {
        selectAutocompleteItem(item);
      });

      dropdown.appendChild(itemEl);
    });

    dropdown.classList.remove("hidden");
    if (destinationInput) destinationInput.setAttribute("aria-expanded", "true");
  }

  async function fetchAutocomplete(query) {
    if (!query || query.trim().length === 0) {
      closeAutocompleteDropdown();
      return;
    }
    try {
      const resp = await apiRequest(
        `/api/destinations/autocomplete?query=${encodeURIComponent(query.trim())}`
      );
      if (resp && resp.ok && resp.suggestions) {
        renderAutocompleteSuggestions(resp);
      } else {
        closeAutocompleteDropdown();
      }
    } catch (err) {
      console.warn("Autocomplete fetch failed:", err);
      closeAutocompleteDropdown();
    }
  }

  // Clear field errors & trigger debounced autocomplete on typing
  if (destinationInput) {
    destinationInput.addEventListener("input", (e) => {
      if (destError) {
        destError.textContent = "";
        destError.classList.remove("active");
      }

      // Reset place ID on manual text modification
      const placeIdInput = document.getElementById("selected-place-id");
      if (placeIdInput) placeIdInput.value = "";

      clearTimeout(autocompleteDebounceTimer);
      const query = e.target.value;
      if (!query || query.trim().length === 0) {
        closeAutocompleteDropdown();
        return;
      }

      autocompleteDebounceTimer = setTimeout(() => {
        fetchAutocomplete(query);
      }, 250);
    });

    destinationInput.addEventListener("keydown", (e) => {
      const dropdown = document.getElementById("destination-autocomplete-dropdown");
      if (!dropdown || dropdown.classList.contains("hidden")) return;

      const items = dropdown.querySelectorAll(".autocomplete-item");
      if (!items.length) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        currentAutocompleteIndex = (currentAutocompleteIndex + 1) % items.length;
        items.forEach((it, idx) => {
          it.classList.toggle("active", idx === currentAutocompleteIndex);
          if (idx === currentAutocompleteIndex) it.scrollIntoView({ block: "nearest" });
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        currentAutocompleteIndex = (currentAutocompleteIndex - 1 + items.length) % items.length;
        items.forEach((it, idx) => {
          it.classList.toggle("active", idx === currentAutocompleteIndex);
          if (idx === currentAutocompleteIndex) it.scrollIntoView({ block: "nearest" });
        });
      } else if (e.key === "Enter" && currentAutocompleteIndex >= 0) {
        e.preventDefault();
        items[currentAutocompleteIndex].click();
      } else if (e.key === "Escape") {
        closeAutocompleteDropdown();
      }
    });

    // Close dropdown on click outside
    document.addEventListener("click", (e) => {
      const wrap = document.querySelector(".autocomplete-wrapper");
      if (wrap && !wrap.contains(e.target)) {
        closeAutocompleteDropdown();
      }
    });
  }

  if (durationInput) {
    durationInput.addEventListener("input", () => {
      if (durationError) {
        durationError.textContent = "";
        durationError.classList.remove("active");
      }
    });
  }

  // Error Banner Dismiss
  if (errorDismissBtn) {
    errorDismissBtn.addEventListener("click", hideErrorBanner);
  }

  // 6. Saved Trips Controls
  if (savedTripsSearch) {
    savedTripsSearch.addEventListener("input", filterAndDisplaySavedTrips);
  }
  if (filterBudget) {
    filterBudget.addEventListener("change", filterAndDisplaySavedTrips);
  }
  if (filterDuration) {
    filterDuration.addEventListener("change", filterAndDisplaySavedTrips);
  }
  if (btnCreateTripShortcut) {
    btnCreateTripShortcut.addEventListener("click", () => switchView("planner"));
  }
  if (btnEmptyStartPlanning) {
    btnEmptyStartPlanning.addEventListener("click", () => switchView("planner"));
  }

  // 7. Delete Confirmation Dialog Listeners
  if (btnCancelDelete) {
    btnCancelDelete.addEventListener("click", closeDeleteConfirm);
  }
  if (btnConfirmDelete) {
    btnConfirmDelete.addEventListener("click", executeTripDeletion);
  }

  // 8. Handle Hash Navigation on load and change (supporting legacy and new hashes)
  function resolveViewFromHash(rawHash) {
    const clean = (rawHash || "").replace("#", "").trim().toLowerCase();
    if (clean === "planner" || clean === "trip-planner") return "planner";
    if (clean === "saved-trips" || clean === "saved-trips-section") return "saved-trips";
    if (clean === "explore" || clean === "destinations") return "explore";
    return "dashboard";
  }

  const initialView = resolveViewFromHash(window.location.hash);
  switchView(initialView, false);

  window.addEventListener("hashchange", () => {
    const targetView = resolveViewFromHash(window.location.hash);
    if (targetView && targetView !== activeViewName) {
      switchView(targetView, false);
    }
  });

  // Initial load of saved trips & destination catalog in background
  loadSavedTrips();
  loadExploreFacets();
});
