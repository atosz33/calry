const API_URL = import.meta.env.VITE_API_URL || "/api";

function createClient() {
  let token = localStorage.getItem("calry_token") || "";

  async function request(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };

    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });

    if (response.status === 204) {
      return null;
    }

    if (!response.ok) {
      let detail = "Request failed";
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        detail = response.statusText || detail;
      }
      throw new Error(detail);
    }

    return response.json();
  }

  return {
    getToken: () => token,
    setToken(nextToken) {
      token = nextToken;
      if (nextToken) {
        localStorage.setItem("calry_token", nextToken);
      } else {
        localStorage.removeItem("calry_token");
      }
    },
    register: (payload) =>
      request("/auth/register", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    login: (payload) =>
      request("/auth/login", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    getMe: () => request("/auth/me"),
    updateMe: (payload) =>
      request("/auth/me", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    getAuditLogs: (limit = 20) => request(`/auth/audit-logs?limit=${limit}`),
    listIngredients: () => request("/ingredients"),
    createIngredient: (payload) =>
      request("/ingredients", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    updateIngredient: (id, payload) =>
      request(`/ingredients/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    deleteIngredient: (id) =>
      request(`/ingredients/${id}`, {
        method: "DELETE",
      }),
    listRecipes: () => request("/recipes"),
    createRecipe: (payload) =>
      request("/recipes", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    updateRecipe: (id, payload) =>
      request(`/recipes/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    deleteRecipe: (id) =>
      request(`/recipes/${id}`, {
        method: "DELETE",
      }),
    suggestIngredientNutrition: (payload) =>
      request("/ai/ingredient-nutrition", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    suggestRecipes: (payload) =>
      request("/ai/recipe-suggestions", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    listMealEntries: (date) => request(`/meal-entries?date=${date}`),
    createMealEntry: (payload) =>
      request("/meal-entries", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    updateMealEntry: (id, payload) =>
      request(`/meal-entries/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    deleteMealEntry: (id) =>
      request(`/meal-entries/${id}`, {
        method: "DELETE",
      }),
    getDashboard: (date) => request(`/users/me/dashboard?date=${date}`),
    getDeficitReport: (days, endDate) =>
      request(`/reports/deficit?days=${days}&end_date=${endDate}`),
    adminListUsers: () => request("/admin/users"),
    adminUpdateUser: (id, payload) =>
      request(`/admin/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    adminListIngredients: () => request("/admin/ingredients"),
    adminCreateIngredient: (payload) =>
      request("/admin/ingredients", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    adminListRecipes: () => request("/admin/recipes"),
    adminListMealEntries: () => request("/admin/meal-entries"),
  };
}

export const api = createClient();
