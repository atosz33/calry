import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "./api";

const mealTypeOptions = [
  { value: "breakfast", labelKey: "mealTypes.breakfast" },
  { value: "lunch", labelKey: "mealTypes.lunch" },
  { value: "dinner", labelKey: "mealTypes.dinner" },
  { value: "snack", labelKey: "mealTypes.snack" },
];

const viewOptions = [
  { value: "overview", labelKey: "nav.overview" },
  { value: "ingredients", labelKey: "nav.ingredients" },
  { value: "recipes", labelKey: "nav.recipes" },
  { value: "meals", labelKey: "nav.meals" },
  { value: "reports", labelKey: "nav.reports" },
  { value: "profile", labelKey: "nav.profile" },
];

const reportPeriods = [7, 30, 90];
const INACTIVITY_TIMEOUT_MS = 30 * 60 * 1000;
const quickDateCount = 5;
const macroFields = [
  { key: "protein", field: "protein_per_100g", labelKey: "macros.proteinShort" },
  { key: "carbs", field: "carbs_per_100g", labelKey: "macros.carbsShort" },
  { key: "fat", field: "fat_per_100g", labelKey: "macros.fatShort" },
];

const emptyAuthForm = {
  name: "",
  email: "",
  password: "",
  gender: "male",
  weight_kg: "",
  height_cm: "",
  age: "",
  daily_calorie_goal: "",
  ai_enabled: false,
};

const emptyIngredientForm = {
  name: "",
  calories_per_100g: "",
  protein_per_100g: "",
  carbs_per_100g: "",
  fat_per_100g: "",
};

const emptyAdminIngredientForm = {
  name: "",
  calories_per_100g: "",
  protein_per_100g: "",
  carbs_per_100g: "",
  fat_per_100g: "",
};

const emptyRecipeLine = {
  ingredient_id: "",
  ingredient_query: "",
  amount_grams: "",
};

const emptyRecipeForm = {
  name: "",
  instructions: "",
  ingredients: [{ ...emptyRecipeLine }],
};

const emptyAiRecipeForm = {
  only_existing_ingredients: true,
  prompt: "",
};

const emptyMealForm = {
  recipe_id: "",
  meal_type: "breakfast",
  grams_eaten: "",
  note: "",
};

function App() {
  const { t, i18n } = useTranslation();
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState(emptyAuthForm);
  const [profileForm, setProfileForm] = useState({
    name: "",
    email: "",
    gender: "male",
    weight_kg: "",
    height_cm: "",
    age: "",
    daily_calorie_goal: "",
    ai_enabled: false,
  });
  const [ingredients, setIngredients] = useState([]);
  const [recipes, setRecipes] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [reports, setReports] = useState({});
  const [auditLogs, setAuditLogs] = useState([]);
  const [adminData, setAdminData] = useState({
    users: [],
    ingredients: [],
    recipes: [],
    mealEntries: [],
  });
  const [adminSection, setAdminSection] = useState("users");
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));
  const [currentView, setCurrentView] = useState("overview");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [ingredientForm, setIngredientForm] = useState(emptyIngredientForm);
  const [adminIngredientForm, setAdminIngredientForm] = useState(emptyAdminIngredientForm);
  const [recipeForm, setRecipeForm] = useState(emptyRecipeForm);
  const [aiRecipeForm, setAiRecipeForm] = useState(emptyAiRecipeForm);
  const [recipeSuggestions, setRecipeSuggestions] = useState([]);
  const [mealForm, setMealForm] = useState(emptyMealForm);
  const [editingIngredientId, setEditingIngredientId] = useState(null);
  const [editingRecipeId, setEditingRecipeId] = useState(null);
  const [editingMealEntryId, setEditingMealEntryId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState("");
  const [error, setError] = useState("");
  const inactivityTimerRef = useRef(null);

  useEffect(() => {
    bootstrap();
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }
    refreshDashboardAndReports(selectedDate);
  }, [selectedDate, user]);

  useEffect(() => {
    if (!user) {
      if (inactivityTimerRef.current) {
        clearTimeout(inactivityTimerRef.current);
      }
      return;
    }

    const resetTimer = () => {
      if (inactivityTimerRef.current) {
        clearTimeout(inactivityTimerRef.current);
      }
      inactivityTimerRef.current = setTimeout(() => {
        logout(t("auth.loggedOutDueToInactivity"));
      }, INACTIVITY_TIMEOUT_MS);
    };

    const events = ["mousemove", "mousedown", "keydown", "touchstart", "scroll"];
    events.forEach((eventName) => window.addEventListener(eventName, resetTimer, { passive: true }));
    resetTimer();

    return () => {
      events.forEach((eventName) => window.removeEventListener(eventName, resetTimer));
      if (inactivityTimerRef.current) {
        clearTimeout(inactivityTimerRef.current);
      }
    };
  }, [t, user]);

  const totalRecipeYield =
    Math.round(
      recipeForm.ingredients.reduce((sum, item) => sum + (Number(item.amount_grams) || 0), 0) * 10
    ) / 10;

  const consumedCalories = dashboard ? dashboard.consumed_calories : 0;
  const calorieTarget = user ? user.daily_calorie_target : 0;
  const estimatedMaintenanceCalories = user ? user.estimated_daily_calories : 0;
  const progressScaleMax = Math.max(estimatedMaintenanceCalories, calorieTarget, consumedCalories, 1);
  const progressPercent = Math.min(100, (consumedCalories / progressScaleMax) * 100);
  const goalMarkerPercent = Math.min(100, (calorieTarget / progressScaleMax) * 100);
  const languageOptions = [
    { value: "hu", label: t("language.hu") },
    { value: "en", label: t("language.en") },
  ];
  const quickDates = buildQuickDates(quickDateCount);

  async function bootstrap() {
    if (!api.getToken()) {
      setLoading(false);
      return;
    }

    try {
      const me = await api.getMe();
      setUser(me);
      hydrateProfileForm(me);
      await refreshCoreData();
    } catch {
      api.setToken("");
    } finally {
      setLoading(false);
    }
  }

  function hydrateProfileForm(nextUser) {
    setProfileForm({
      name: nextUser.name,
      email: nextUser.email,
      gender: nextUser.gender,
      weight_kg: String(nextUser.weight_kg),
      height_cm: String(nextUser.height_cm),
      age: nextUser.age ? String(nextUser.age) : "",
      daily_calorie_goal: nextUser.daily_calorie_goal ? String(nextUser.daily_calorie_goal) : "",
      ai_enabled: Boolean(nextUser.ai_enabled),
    });
  }

  async function refreshCoreData() {
    const [ingredientData, recipeData, auditData] = await Promise.all([
      api.listIngredients(),
      api.listRecipes(),
      api.getAuditLogs(),
    ]);
    setIngredients(ingredientData);
    setRecipes(recipeData);
    setAuditLogs(auditData);
    await refreshDashboardAndReports(selectedDate);
  }

  async function refreshAdminData() {
    if (!user?.is_admin) {
      return;
    }

    const [users, adminIngredients, adminRecipes, adminMealEntries] = await Promise.all([
      api.adminListUsers(),
      api.adminListIngredients(),
      api.adminListRecipes(),
      api.adminListMealEntries(),
    ]);
    setAdminData({
      users,
      ingredients: adminIngredients,
      recipes: adminRecipes,
      mealEntries: adminMealEntries,
    });
  }

  async function refreshDashboardAndReports(date) {
    const [dashboardData, report7, report30, report90] = await Promise.all([
      api.getDashboard(date),
      api.getDeficitReport(7, date),
      api.getDeficitReport(30, date),
      api.getDeficitReport(90, date),
    ]);
    setDashboard(dashboardData);
    setReports({
      7: report7,
      30: report30,
      90: report90,
    });
  }

  async function handleAuthSubmit(event) {
    event.preventDefault();
    setSubmitting("auth");
    setError("");
    try {
      const action = authMode === "register" ? api.register : api.login;
      const payload =
        authMode === "register"
          ? {
              ...authForm,
              email: authForm.email.trim().toLowerCase(),
              weight_kg: Number(authForm.weight_kg),
              height_cm: Number(authForm.height_cm),
              age: authForm.age ? Number(authForm.age) : null,
              daily_calorie_goal: authForm.daily_calorie_goal
                ? Number(authForm.daily_calorie_goal)
                : null,
            }
          : {
              email: authForm.email.trim().toLowerCase(),
              password: authForm.password,
            };
      const result = await action(payload);
      api.setToken(result.token);
      setUser(result.user);
      hydrateProfileForm(result.user);
      setAuthForm(emptyAuthForm);
      await refreshCoreData();
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleProfileSubmit(event) {
    event.preventDefault();
    setSubmitting("profile");
    setError("");
    try {
      const updated = await api.updateMe({
        ...profileForm,
        email: profileForm.email.trim().toLowerCase(),
        weight_kg: Number(profileForm.weight_kg),
        height_cm: Number(profileForm.height_cm),
        age: profileForm.age ? Number(profileForm.age) : null,
        daily_calorie_goal: profileForm.daily_calorie_goal
          ? Number(profileForm.daily_calorie_goal)
          : null,
        ai_enabled: Boolean(profileForm.ai_enabled),
      });
      setUser(updated);
      hydrateProfileForm(updated);
      await refreshDashboardAndReports(selectedDate);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleIngredientSubmit(event) {
    event.preventDefault();
    setSubmitting("ingredient");
    setError("");
    try {
      const payload = buildIngredientPayload(ingredientForm);
      if (editingIngredientId) {
        await api.updateIngredient(editingIngredientId, payload);
      } else {
        await api.createIngredient(payload);
      }
      resetIngredientForm();
      await refreshCoreData();
      setCurrentView("ingredients");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleAdminIngredientSubmit(event) {
    event.preventDefault();
    setSubmitting("adminIngredient");
    setError("");
    try {
      await api.adminCreateIngredient(buildIngredientPayload(adminIngredientForm));
      setAdminIngredientForm(emptyAdminIngredientForm);
      await refreshAdminData();
      await refreshCoreData();
      setAdminSection("ingredients");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleAdminUserAiToggle(userId, aiEnabled) {
    setSubmitting(`adminUserAi:${userId}`);
    setError("");
    try {
      const updatedUser = await api.adminUpdateUser(userId, { ai_enabled: aiEnabled });
      setAdminData((currentData) => ({
        ...currentData,
        users: currentData.users.map((adminUser) =>
          adminUser.id === userId ? updatedUser : adminUser
        ),
      }));
      if (user?.id === userId) {
        setUser(updatedUser);
        hydrateProfileForm(updatedUser);
      }
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleSuggestIngredientNutrition() {
    if (!ingredientForm.name.trim()) {
      return;
    }
    setSubmitting("ingredientAi");
    setError("");
    try {
      const suggestion = await api.suggestIngredientNutrition({ name: ingredientForm.name.trim() });
      setIngredientForm((current) => ({
        ...current,
        calories_per_100g: String(suggestion.calories_per_100g),
        protein_per_100g: String(suggestion.protein_per_100g),
        carbs_per_100g: String(suggestion.carbs_per_100g),
        fat_per_100g: String(suggestion.fat_per_100g),
      }));
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleSuggestRecipes() {
    setSubmitting("recipeAi");
    setError("");
    try {
      const suggestions = await api.suggestRecipes({
        only_existing_ingredients: aiRecipeForm.only_existing_ingredients,
        prompt: aiRecipeForm.prompt || null,
      });
      setRecipeSuggestions(suggestions);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  function useRecipeSuggestion(suggestion) {
    const usableIngredients = suggestion.ingredients
      .filter((item) => item.ingredient_id)
      .map((item) => ({
        ingredient_id: String(item.ingredient_id),
        ingredient_query: item.ingredient_name,
        amount_grams: String(item.amount_grams),
      }));
    setEditingRecipeId(null);
    setRecipeForm({
      name: suggestion.name,
      instructions: suggestion.instructions || "",
      ingredients: usableIngredients.length ? usableIngredients : [{ ...emptyRecipeLine }],
    });
    setCurrentView("recipes");
  }

  async function handleRecipeSubmit(event) {
    event.preventDefault();
    setSubmitting("recipe");
    setError("");
    try {
      const payload = {
        name: recipeForm.name,
        instructions: recipeForm.instructions || null,
        ingredients: recipeForm.ingredients.map((item) => ({
          ingredient_id: Number(item.ingredient_id),
          amount_grams: Number(item.amount_grams),
        })),
      };
      if (editingRecipeId) {
        await api.updateRecipe(editingRecipeId, payload);
      } else {
        await api.createRecipe(payload);
      }
      resetRecipeForm();
      await refreshCoreData();
      setCurrentView("recipes");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleMealSubmit(event) {
    event.preventDefault();
    setSubmitting("meal");
    setError("");
    try {
      const selectedRecipe = recipes.find((recipe) => String(recipe.id) === mealForm.recipe_id);
      const newMealCalories = selectedRecipe
        ? (Number(mealForm.grams_eaten) * selectedRecipe.calories_per_100g) / 100
        : 0;
      const currentMealCalories = editingMealEntryId
        ? findMealEntryCalories(editingMealEntryId, dashboard)
        : 0;
      const projectedTotal = consumedCalories - currentMealCalories + newMealCalories;

      if (projectedTotal > calorieTarget) {
        const shouldContinue = window.confirm(
          t("meals.overTargetConfirm", {
            projected: Math.round(projectedTotal),
            target: calorieTarget,
          })
        );
        if (!shouldContinue) {
          setSubmitting("");
          return;
        }
      }

      const payload = {
        recipe_id: Number(mealForm.recipe_id),
        meal_type: mealForm.meal_type,
        grams_eaten: Number(mealForm.grams_eaten),
        date: selectedDate,
        note: mealForm.note || null,
      };

      if (editingMealEntryId) {
        await api.updateMealEntry(editingMealEntryId, payload);
      } else {
        await api.createMealEntry(payload);
      }

      resetMealForm();
      await refreshDashboardAndReports(selectedDate);
      setCurrentView("overview");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setSubmitting("");
    }
  }

  async function handleDeleteIngredient(id) {
    setError("");
    try {
      await api.deleteIngredient(id);
      if (editingIngredientId === id) {
        resetIngredientForm();
      }
      await refreshCoreData();
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  async function handleDeleteRecipe(id) {
    setError("");
    try {
      await api.deleteRecipe(id);
      if (editingRecipeId === id) {
        resetRecipeForm();
      }
      await refreshCoreData();
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  async function handleDeleteMealEntry(id) {
    setError("");
    try {
      await api.deleteMealEntry(id);
      if (editingMealEntryId === id) {
        resetMealForm();
      }
      await refreshDashboardAndReports(selectedDate);
    } catch (deleteError) {
      setError(deleteError.message);
    }
  }

  function startEditingIngredient(ingredient) {
    setEditingIngredientId(ingredient.id);
    setIngredientForm({
      name: ingredient.name,
      calories_per_100g: String(ingredient.calories_per_100g),
      protein_per_100g: String(ingredient.protein_per_100g),
      carbs_per_100g: String(ingredient.carbs_per_100g),
      fat_per_100g: String(ingredient.fat_per_100g),
    });
    setCurrentView("ingredients");
  }

  function startEditingRecipe(recipe) {
    setEditingRecipeId(recipe.id);
    setRecipeForm({
      name: recipe.name,
      instructions: recipe.instructions || "",
      ingredients: recipe.ingredients.map((item) => ({
        ingredient_id: String(item.ingredient_id),
        ingredient_query: item.ingredient_name,
        amount_grams: String(item.amount_grams),
      })),
    });
    setCurrentView("recipes");
  }

  function startEditingMealEntry(entry) {
    setEditingMealEntryId(entry.id);
    setMealForm({
      recipe_id: String(entry.recipe_id),
      meal_type: entry.meal_type,
      grams_eaten: String(entry.grams_eaten),
      note: entry.note || "",
    });
    setCurrentView("meals");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function addRecipeLine() {
    setRecipeForm((current) => ({
      ...current,
      ingredients: [...current.ingredients, { ...emptyRecipeLine }],
    }));
  }

  function updateRecipeLine(index, field, value) {
    setRecipeForm((current) => ({
      ...current,
      ingredients: current.ingredients.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item
      ),
    }));
  }

  function updateRecipeIngredientQuery(index, value) {
    setRecipeForm((current) => ({
      ...current,
      ingredients: current.ingredients.map((item, itemIndex) =>
        itemIndex === index
          ? {
              ...item,
              ingredient_query: value,
              ingredient_id:
                ingredients.find(
                  (ingredient) => ingredient.name.toLocaleLowerCase() === value.toLocaleLowerCase()
                )?.id || "",
            }
          : item
      ),
    }));
  }

  function removeRecipeLine(index) {
    setRecipeForm((current) => ({
      ...current,
      ingredients:
        current.ingredients.length === 1
          ? current.ingredients
          : current.ingredients.filter((_, itemIndex) => itemIndex !== index),
    }));
  }

  function resetIngredientForm() {
    setEditingIngredientId(null);
    setIngredientForm(emptyIngredientForm);
  }

  function resetRecipeForm() {
    setEditingRecipeId(null);
    setRecipeForm(emptyRecipeForm);
  }

  function resetMealForm() {
    setEditingMealEntryId(null);
    setMealForm(emptyMealForm);
  }

  async function openAdmin() {
    setCurrentView("admin");
    setError("");
    await refreshAdminData();
  }

  function logout(reason = "") {
    api.setToken("");
    setUser(null);
    setAuthMode("login");
    setAuthForm(emptyAuthForm);
    setDashboard(null);
    setReports({});
    setAuditLogs([]);
    setIngredients([]);
    setRecipes([]);
    setAdminData({ users: [], ingredients: [], recipes: [], mealEntries: [] });
    setError(typeof reason === "string" ? reason : "");
    setCurrentView("overview");
  }

  if (loading) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <p className="empty-state">{t("common.loading")}</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <p className="eyebrow">{t("auth.appName")}</p>
          <h1>{authMode === "login" ? t("auth.signIn") : t("auth.createAccount")}</h1>
          <p className="auth-copy">
            {authMode === "login"
              ? t("auth.signInCopy")
              : t("auth.registerCopy")}
          </p>
          {error ? <div className="error-banner">{error}</div> : null}
          <form className="stack-form" onSubmit={handleAuthSubmit}>
            {authMode === "register" ? (
              <>
                <input
                  placeholder={t("placeholders.name")}
                  value={authForm.name}
                  onChange={(event) => setAuthForm({ ...authForm, name: event.target.value })}
                  required
                />
                <div className="form-row">
                  <select
                    value={authForm.gender}
                    onChange={(event) => setAuthForm({ ...authForm, gender: event.target.value })}
                  >
                    <option value="male">{t("gender.male")}</option>
                    <option value="female">{t("gender.female")}</option>
                  </select>
                  <input
                    type="number"
                    placeholder={t("fields.age")}
                    value={authForm.age}
                    onChange={(event) => setAuthForm({ ...authForm, age: event.target.value })}
                  />
                </div>
                <div className="form-row">
                  <input
                    type="number"
                    step="0.1"
                    placeholder={t("fields.weightKg")}
                    value={authForm.weight_kg}
                    onChange={(event) =>
                      setAuthForm({ ...authForm, weight_kg: event.target.value })
                    }
                    required
                  />
                  <input
                    type="number"
                    step="0.1"
                    placeholder={t("fields.heightCm")}
                    value={authForm.height_cm}
                    onChange={(event) =>
                      setAuthForm({ ...authForm, height_cm: event.target.value })
                    }
                    required
                  />
                </div>
                <input
                  type="number"
                  min="1"
                  placeholder={t("fields.dailyCalorieGoalOptional")}
                  value={authForm.daily_calorie_goal}
                  onChange={(event) =>
                    setAuthForm({ ...authForm, daily_calorie_goal: event.target.value })
                  }
                />
              </>
            ) : null}
            <input
              type="email"
              placeholder={t("placeholders.email")}
              value={authForm.email}
              onChange={(event) => setAuthForm({ ...authForm, email: event.target.value })}
              required
            />
            <Field label={t("fields.password")}>
              <div className="password-row">
                <input
                  type={passwordVisible ? "text" : "password"}
                  placeholder={t("placeholders.password")}
                  value={authForm.password}
                  onChange={(event) => setAuthForm({ ...authForm, password: event.target.value })}
                  required
                />
                <button
                  type="button"
                  className="ghost-button password-toggle"
                  onClick={() => setPasswordVisible((current) => !current)}
                >
                  {passwordVisible ? t("auth.hidePassword") : t("auth.showPassword")}
                </button>
              </div>
            </Field>
            {authMode === "register" ? (
              <p className="helper-text">
                {t("auth.passwordRules")}
              </p>
            ) : null}
            <button type="submit" disabled={submitting === "auth"}>
              {submitting === "auth"
                ? t("auth.working")
                : authMode === "login"
                  ? t("auth.signIn")
                  : t("auth.createAccount")}
            </button>
          </form>
          <button
            type="button"
            className="ghost-button auth-secondary-button"
            onClick={() => {
              setAuthMode(authMode === "login" ? "register" : "login");
              setError("");
            }}
          >
            {authMode === "login" ? t("auth.needAccount") : t("auth.alreadyHaveAccount")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className="app-frame">
        <header className="topbar">
          <div>
            <p className="eyebrow">{t("dashboard.tracker")}</p>
          </div>
          <div className="topbar-actions">
            <input
              className="date-input"
              type="date"
              value={selectedDate}
              onChange={(event) => setSelectedDate(event.target.value)}
            />
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        <section className="hero-card">
          <div className="hero-head">
            <div>
              <span className="muted-label">{t("dashboard.signedInAs")}</span>
              <h2>{user.name}</h2>
              <p className="auth-copy">{user.email}</p>
            </div>
            <div className="target-pill">{t("dashboard.targetPill", { value: user.daily_calorie_target })}</div>
          </div>

          <div className="quick-date-row" aria-label={t("dashboard.quickDateLabel")}>
            {quickDates.map((day, index) => (
              <button
                key={day.isoDate}
                type="button"
                className={selectedDate === day.isoDate ? "quick-date-card active" : "quick-date-card"}
                onClick={() => setSelectedDate(day.isoDate)}
              >
                <span>{index === 0 ? t("common.today") : formatWeekday(day.date, i18n.language)}</span>
                <strong>{formatDayMonth(day.date, i18n.language)}</strong>
              </button>
            ))}
          </div>

          <div className="stats-grid">
            <div className="stat-card accent-blue">
              <span>{t("dashboard.consumed")}</span>
              <strong>{Math.round(consumedCalories)} {t("common.kcal")}</strong>
            </div>
            <div className="stat-card accent-sand">
              <span>{t("dashboard.remaining")}</span>
              <strong>{dashboard ? Math.round(dashboard.remaining_calories) : 0} {t("common.kcal")}</strong>
            </div>
          </div>
          <MacroSummary
            className="dashboard-macros"
            values={{
              protein: dashboard?.consumed_protein || 0,
              carbs: dashboard?.consumed_carbs || 0,
              fat: dashboard?.consumed_fat || 0,
            }}
            t={t}
          />

          <div className="progress-card">
            <div className="progress-meta">
              <span>{t("dashboard.dailyCalories")}</span>
              <span>
                {Math.round(consumedCalories)} / {calorieTarget}
              </span>
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
              <div className="goal-marker" style={{ left: `${goalMarkerPercent}%` }} />
            </div>
            <p className="progress-note">{t("dashboard.redLineNote")}</p>
          </div>
        </section>

        <nav className="section-nav" aria-label="App sections">
          {viewOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              className={currentView === option.value ? "nav-chip active" : "nav-chip"}
              onClick={() => setCurrentView(option.value)}
            >
              {t(option.labelKey)}
            </button>
          ))}
        </nav>

        {currentView === "overview" ? (
          <section className="content-grid single-column">
            <div className="main-column">
              <Panel
                title={t("overview.diary")}
                subtitle={t("overview.mealsForSelectedDate")}
                actionLabel={t("common.groups", { count: dashboard?.meals.length || 0 })}
              >
                {dashboard?.meals.length ? (
                  <MealGroups
                    dashboard={dashboard}
                    t={t}
                    onEdit={startEditingMealEntry}
                    onDelete={handleDeleteMealEntry}
                  />
                ) : (
                  <p className="empty-state">{t("overview.noMeals")}</p>
                )}
              </Panel>
            </div>
          </section>
        ) : null}

        {currentView === "ingredients" ? (
          <section className="content-grid">
            <div className="main-column">
              <Panel title={t("ingredients.title")} subtitle={t("ingredients.subtitle")}>
                <div className="recipe-cards">
                  {ingredients.length ? (
                    ingredients.map((ingredient) => (
                      <article className="recipe-card" key={ingredient.id}>
                        <div className="recipe-card-head">
                          <div>
                            <h3>{ingredient.name}</h3>
                            <p>{t("recipes.caloriesPer100g", { value: ingredient.calories_per_100g })}</p>
                            <MacroSummary
                              values={{
                                protein: ingredient.protein_per_100g,
                                carbs: ingredient.carbs_per_100g,
                                fat: ingredient.fat_per_100g,
                              }}
                              suffix={t("macros.per100gSuffix")}
                              t={t}
                            />
                          </div>
                          <div className="inline-actions">
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => startEditingIngredient(ingredient)}
                            >
                              {t("common.edit")}
                            </button>
                            <button
                              type="button"
                              className="danger-button"
                              onClick={() => handleDeleteIngredient(ingredient.id)}
                            >
                              {t("common.delete")}
                            </button>
                          </div>
                        </div>
                      </article>
                    ))
                  ) : (
                    <p className="empty-state">{t("ingredients.empty")}</p>
                  )}
                </div>
              </Panel>
            </div>
            <aside className="side-column">
              <Panel
                title={editingIngredientId ? t("ingredients.editTitle") : t("ingredients.addTitle")}
                subtitle={t("ingredients.zeroCaloriesHelp")}
              >
                <form className="stack-form" onSubmit={handleIngredientSubmit}>
                  <Field label={t("fields.ingredientName")}>
                    <div className="ai-field-row">
                      <input
                        placeholder={t("placeholders.ingredientName")}
                        value={ingredientForm.name}
                        onChange={(event) =>
                          setIngredientForm({ ...ingredientForm, name: event.target.value })
                        }
                        required
                      />
                      <button
                        type="button"
                        className="ai-square-button"
                        onClick={handleSuggestIngredientNutrition}
                        disabled={!user.ai_enabled || submitting === "ingredientAi" || !ingredientForm.name.trim()}
                        title={user.ai_enabled ? t("ai.fillNutrition") : t("ai.disabled")}
                      >
                        {submitting === "ingredientAi" ? "..." : "AI"}
                      </button>
                    </div>
                  </Field>
                  <Field label={t("fields.caloriesPer100g")}>
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      placeholder={t("placeholders.caloriesPer100g")}
                      value={ingredientForm.calories_per_100g}
                      onChange={(event) =>
                        setIngredientForm({
                          ...ingredientForm,
                          calories_per_100g: event.target.value,
                        })
                      }
                      required
                    />
                  </Field>
                  <MacroInputs form={ingredientForm} setForm={setIngredientForm} t={t} />
                  <button type="submit" disabled={submitting === "ingredient"}>
                    {submitting === "ingredient"
                      ? t("common.saving")
                      : editingIngredientId
                        ? t("ingredients.updateButton")
                        : t("ingredients.addButton")}
                  </button>
                  {editingIngredientId ? (
                    <button type="button" className="ghost-button" onClick={resetIngredientForm}>
                      {t("common.cancelEditing")}
                    </button>
                  ) : null}
                </form>
              </Panel>
            </aside>
          </section>
        ) : null}

        {currentView === "recipes" ? (
          <section className="content-grid">
            <div className="main-column">
              <Panel title={t("recipes.title")} subtitle={t("recipes.subtitle")}>
                <div className="recipe-cards">
                  {recipes.length ? (
                    recipes.map((recipe) => (
                      <article className="recipe-card" key={recipe.id}>
                        <div className="recipe-card-head">
                          <div>
                            <h3>{recipe.name}</h3>
                            <p>{t("recipes.recipeWeight", { value: Math.round(recipe.total_yield_grams) })}</p>
                          </div>
                          <div className="card-actions">
                            <span>{t("recipes.caloriesPer100g", { value: Math.round(recipe.calories_per_100g) })}</span>
                            <div className="inline-actions">
                              <button
                                type="button"
                                className="secondary-button"
                                onClick={() => startEditingRecipe(recipe)}
                              >
                                {t("common.edit")}
                              </button>
                              <button
                                type="button"
                                className="danger-button"
                                onClick={() => handleDeleteRecipe(recipe.id)}
                              >
                                {t("common.delete")}
                              </button>
                            </div>
                          </div>
                        </div>
                        <p className="recipe-summary">
                          {t("recipes.totalCaloriesFromIngredients", {
                            calories: Math.round(recipe.total_calories),
                            count: recipe.ingredients.length,
                          })}
                        </p>
                        {recipe.instructions ? (
                          <p className="recipe-instructions">{recipe.instructions}</p>
                        ) : null}
                        <MacroSummary
                          values={{
                            protein: recipe.total_protein,
                            carbs: recipe.total_carbs,
                            fat: recipe.total_fat,
                          }}
                          t={t}
                        />
                      </article>
                    ))
                  ) : (
                    <p className="empty-state">{t("recipes.empty")}</p>
                  )}
                </div>
              </Panel>
              <Panel title={t("ai.recipeIdeasTitle")} subtitle={t("ai.recipeIdeasSubtitle")}>
                <div className="ai-recipe-box">
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={aiRecipeForm.only_existing_ingredients}
                      onChange={(event) =>
                        setAiRecipeForm({
                          ...aiRecipeForm,
                          only_existing_ingredients: event.target.checked,
                        })
                      }
                    />
                    <span>{t("ai.onlyExistingIngredients")}</span>
                  </label>
                  <input
                    placeholder={t("placeholders.recipeIdeaPrompt")}
                    value={aiRecipeForm.prompt}
                    onChange={(event) => setAiRecipeForm({ ...aiRecipeForm, prompt: event.target.value })}
                  />
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={handleSuggestRecipes}
                    disabled={!user.ai_enabled || submitting === "recipeAi"}
                    title={user.ai_enabled ? t("ai.generateRecipes") : t("ai.disabled")}
                  >
                    {submitting === "recipeAi" ? t("ai.generating") : t("ai.generateRecipes")}
                  </button>
                  {recipeSuggestions.length ? (
                    <div className="recipe-cards">
                      {recipeSuggestions.map((suggestion, index) => (
                        <article className="recipe-card" key={`${suggestion.name}-${index}`}>
                          <div className="recipe-card-head">
                            <div>
                              <h3>{suggestion.name}</h3>
                              <p>
                                {t("common.items", {
                                  count: suggestion.ingredients.length,
                                })}
                              </p>
                            </div>
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => useRecipeSuggestion(suggestion)}
                            >
                              {t("ai.useRecipe")}
                            </button>
                          </div>
                          {suggestion.instructions ? (
                            <p className="recipe-instructions">{suggestion.instructions}</p>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  ) : null}
                </div>
              </Panel>
            </div>
            <aside className="side-column">
              <Panel
                title={editingRecipeId ? t("recipes.editTitle") : t("recipes.addTitle")}
                subtitle={t("recipes.totalWeightHelp")}
              >
                <form className="stack-form" onSubmit={handleRecipeSubmit}>
                  <Field label={t("fields.recipeName")}>
                    <input
                      placeholder={t("placeholders.recipeName")}
                      value={recipeForm.name}
                      onChange={(event) => setRecipeForm({ ...recipeForm, name: event.target.value })}
                      required
                    />
                  </Field>
                  <Field label={t("fields.instructions")}>
                    <textarea
                      placeholder={t("placeholders.instructions")}
                      value={recipeForm.instructions}
                      onChange={(event) => setRecipeForm({ ...recipeForm, instructions: event.target.value })}
                    />
                  </Field>
                  <Field label={t("fields.calculatedTotalWeight")}>
                    <div className="yield-pill">{t("recipes.totalWeightValue", { value: totalRecipeYield })}</div>
                  </Field>
                  <div className="line-items">
                    {recipeForm.ingredients.map((line, index) => {
                      const matchingIngredients = findMatchingIngredients(ingredients, line.ingredient_query);

                      return (
                        <div className="line-item" key={`${index}-${line.ingredient_id}-${index}`}>
                          <Field label={t("recipes.ingredientRow", { index: index + 1 })}>
                            <input
                              list={`recipe-ingredient-options-${index}`}
                              placeholder={t("placeholders.selectIngredient")}
                              value={line.ingredient_query}
                              onChange={(event) =>
                                updateRecipeIngredientQuery(index, event.target.value)
                              }
                              required
                            />
                            <datalist id={`recipe-ingredient-options-${index}`}>
                              {matchingIngredients.map((ingredient) => (
                                <option key={ingredient.id} value={ingredient.name} />
                              ))}
                            </datalist>
                          </Field>
                          <Field label={t("fields.amountInGrams")}>
                            <input
                              type="number"
                              step="0.1"
                              placeholder={t("placeholders.amountInGrams")}
                              value={line.amount_grams}
                              onChange={(event) =>
                                updateRecipeLine(index, "amount_grams", event.target.value)
                              }
                              required
                            />
                          </Field>
                          <button
                            type="button"
                            className="remove-line-button"
                            aria-label={t("common.remove")}
                            onClick={() => removeRecipeLine(index)}
                          >
                            X
                          </button>
                        </div>
                      );
                    })}
                  </div>
                  <button type="button" className="secondary-button" onClick={addRecipeLine}>
                    {t("recipes.addIngredientRow")}
                  </button>
                  <button type="submit" disabled={submitting === "recipe" || !ingredients.length}>
                    {submitting === "recipe"
                      ? t("common.saving")
                      : editingRecipeId
                        ? t("recipes.updateButton")
                        : t("recipes.saveButton")}
                  </button>
                  {editingRecipeId ? (
                    <button type="button" className="ghost-button" onClick={resetRecipeForm}>
                      {t("common.cancelEditing")}
                    </button>
                  ) : null}
                </form>
              </Panel>
            </aside>
          </section>
        ) : null}

        {currentView === "meals" ? (
          <section className="content-grid">
            <div className="main-column">
              <Panel title={t("meals.title")} subtitle={t("meals.subtitle")}>
                {dashboard?.meals.length ? (
                  <MealGroups
                    dashboard={dashboard}
                    t={t}
                    onEdit={startEditingMealEntry}
                    onDelete={handleDeleteMealEntry}
                  />
                ) : (
                  <p className="empty-state">{t("overview.noMeals")}</p>
                )}
              </Panel>
            </div>
            <aside className="side-column">
              <Panel
                title={editingMealEntryId ? t("meals.editTitle") : t("meals.addTitle")}
                subtitle={t("meals.help")}
              >
                <form className="stack-form" onSubmit={handleMealSubmit}>
                  <Field label={t("fields.recipe")}>
                    <select
                      value={mealForm.recipe_id}
                      onChange={(event) => setMealForm({ ...mealForm, recipe_id: event.target.value })}
                      required
                    >
                      <option value="">{t("placeholders.selectRecipe")}</option>
                      {recipes.map((recipe) => (
                        <option key={recipe.id} value={recipe.id}>
                          {recipe.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <div className="form-row">
                    <Field label={t("fields.mealType")}>
                      <select
                        value={mealForm.meal_type}
                        onChange={(event) => setMealForm({ ...mealForm, meal_type: event.target.value })}
                      >
                        {mealTypeOptions.map((option) => (
                          <option key={option.value} value={option.value}>
                            {t(option.labelKey)}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label={t("fields.gramsEaten")}>
                      <input
                        type="number"
                        step="0.1"
                        placeholder={t("placeholders.gramsEaten")}
                        value={mealForm.grams_eaten}
                        onChange={(event) =>
                          setMealForm({ ...mealForm, grams_eaten: event.target.value })
                        }
                        required
                      />
                    </Field>
                  </div>
                  <Field label={t("fields.note")}>
                    <input
                      placeholder={t("placeholders.optionalNote")}
                      value={mealForm.note}
                      onChange={(event) => setMealForm({ ...mealForm, note: event.target.value })}
                    />
                  </Field>
                  <div className="log-submit-wrap">
                    <button type="submit" disabled={submitting === "meal"}>
                      {submitting === "meal"
                        ? t("common.saving")
                        : editingMealEntryId
                          ? t("meals.updateButton")
                          : t("meals.logButton")}
                    </button>
                  </div>
                  {editingMealEntryId ? (
                    <button type="button" className="ghost-button" onClick={resetMealForm}>
                      {t("common.cancelEditing")}
                    </button>
                  ) : null}
                </form>
              </Panel>
            </aside>
          </section>
        ) : null}

        {currentView === "reports" ? (
          <section className="content-grid single-column">
            <div className="main-column">
              <Panel title={t("reports.title")} subtitle={t("reports.subtitle")}>
                <div className="report-grid">
                  {reportPeriods.map((days) => {
                    const report = reports[days];
                    return (
                      <article className="report-card" key={days}>
                        <div className="recipe-card-head">
                          <div>
                            <h3>{t("reports.lastDays", { days })}</h3>
                            <p>{t("reports.deficitVersusTarget")}</p>
                          </div>
                          <span>{report ? Math.round(report.total_deficit) : 0} {t("common.kcal")}</span>
                        </div>
                        <div className="report-stats">
                          <div>
                            <span>{t("reports.totalTarget")}</span>
                            <strong>{report ? Math.round(report.total_target_calories) : 0}</strong>
                          </div>
                          <div>
                            <span>{t("reports.totalConsumed")}</span>
                            <strong>{report ? Math.round(report.total_consumed_calories) : 0}</strong>
                          </div>
                          <div>
                            <span>{t("reports.avgDailyDeficit")}</span>
                            <strong>{report ? Math.round(report.average_daily_deficit) : 0}</strong>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </Panel>
            </div>
          </section>
        ) : null}

        {currentView === "profile" ? (
          <section className="content-grid single-column">
            <aside className="side-column profile-column">
              <Panel title={t("profile.title")} subtitle={t("profile.subtitle")}>
                <form className="stack-form" onSubmit={handleProfileSubmit}>
                  <Field label={t("fields.fullName")}>
                    <input
                      placeholder={t("placeholders.name")}
                      value={profileForm.name}
                      onChange={(event) => setProfileForm({ ...profileForm, name: event.target.value })}
                      required
                    />
                  </Field>
                  <Field label={t("fields.emailAddress")}>
                    <input
                      type="email"
                      placeholder={t("placeholders.email")}
                      value={profileForm.email}
                      onChange={(event) => setProfileForm({ ...profileForm, email: event.target.value })}
                      required
                    />
                  </Field>
                  <div className="form-row">
                    <Field label={t("fields.gender")}>
                      <select
                        value={profileForm.gender}
                        onChange={(event) => setProfileForm({ ...profileForm, gender: event.target.value })}
                      >
                        <option value="male">{t("gender.male")}</option>
                        <option value="female">{t("gender.female")}</option>
                      </select>
                    </Field>
                    <Field label={t("fields.age")}>
                      <input
                        type="number"
                        placeholder={t("fields.ageYears")}
                        value={profileForm.age}
                        onChange={(event) => setProfileForm({ ...profileForm, age: event.target.value })}
                      />
                    </Field>
                  </div>
                  <div className="form-row">
                    <Field label={t("fields.weightKg")}>
                      <input
                        type="number"
                        step="0.1"
                        placeholder={t("fields.weightKilograms")}
                        value={profileForm.weight_kg}
                        onChange={(event) =>
                          setProfileForm({ ...profileForm, weight_kg: event.target.value })
                        }
                        required
                      />
                    </Field>
                    <Field label={t("fields.heightCm")}>
                      <input
                        type="number"
                        step="0.1"
                        placeholder={t("fields.heightCentimeters")}
                        value={profileForm.height_cm}
                        onChange={(event) =>
                          setProfileForm({ ...profileForm, height_cm: event.target.value })
                        }
                        required
                      />
                    </Field>
                  </div>
                  <Field label={t("fields.dailyCalorieGoal")}>
                    <input
                      type="number"
                      min="1"
                      placeholder={t("placeholders.dailyCalorieGoal")}
                      value={profileForm.daily_calorie_goal}
                      onChange={(event) =>
                        setProfileForm({ ...profileForm, daily_calorie_goal: event.target.value })
                      }
                    />
                  </Field>
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={profileForm.ai_enabled}
                      onChange={(event) =>
                        setProfileForm({ ...profileForm, ai_enabled: event.target.checked })
                      }
                    />
                    <span>{t("profile.aiEnabled")}</span>
                  </label>
                  <Field label={t("language.label")}>
                    <LanguageSwitcher
                      value={i18n.language}
                      options={languageOptions}
                      onChange={(event) => i18n.changeLanguage(event.target.value)}
                    />
                  </Field>
                  <div className="info-card">
                    <span>{t("profile.estimatedMaintenance")}</span>
                    <strong>{t("profile.perDay", { value: user.estimated_daily_calories })}</strong>
                  </div>
                  <div className="info-card">
                    <span>{t("profile.activeTarget")}</span>
                    <strong>{t("profile.perDay", { value: user.daily_calorie_target })}</strong>
                  </div>
                  <button type="submit" disabled={submitting === "profile"}>
                    {submitting === "profile" ? t("common.saving") : t("profile.saveButton")}
                  </button>
                </form>
                {auditLogs.length ? (
                  <div className="audit-log">
                    <h3>{t("profile.recentLoginActivity")}</h3>
                    <div className="audit-log-list">
                      {auditLogs.slice(0, 5).map((item) => (
                        <div className="audit-log-item" key={item.id}>
                          <strong>{t(`audit.${item.outcome}`, { defaultValue: item.outcome })}</strong>
                          <span>{new Date(item.created_at).toLocaleString()}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </Panel>
            </aside>
          </section>
        ) : null}

        {currentView === "admin" && user.is_admin ? (
          <AdminPanel
            data={adminData}
            activeSection={adminSection}
            setActiveSection={setAdminSection}
            ingredientForm={adminIngredientForm}
            setIngredientForm={setAdminIngredientForm}
            onIngredientSubmit={handleAdminIngredientSubmit}
            onUserAiToggle={handleAdminUserAiToggle}
            submitting={submitting}
            t={t}
          />
        ) : null}

        <section className="footer-actions">
          <button type="button" className="ghost-button footer-action-button" onClick={() => setCurrentView("reports")}>
            {t("common.report")}
          </button>
          <button type="button" className="ghost-button footer-action-button" onClick={() => logout()}>
            {t("common.logOut")}
          </button>
          {user.is_admin ? (
            <button type="button" className="ghost-button footer-action-button" onClick={openAdmin}>
              {t("admin.open")}
            </button>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function AdminPanel({
  data,
  activeSection,
  setActiveSection,
  ingredientForm,
  setIngredientForm,
  onIngredientSubmit,
  onUserAiToggle,
  submitting,
  t,
}) {
  const sections = [
    { value: "users", label: t("admin.users") },
    { value: "ingredients", label: t("admin.ingredients") },
    { value: "recipes", label: t("admin.recipes") },
    { value: "meals", label: t("admin.meals") },
  ];

  return (
    <section className="admin-layout">
      <aside className="admin-sidebar">
        <h2>{t("admin.title")}</h2>
        <div className="admin-menu">
          {sections.map((section) => (
            <button
              key={section.value}
              type="button"
              className={activeSection === section.value ? "admin-menu-button active" : "admin-menu-button"}
              onClick={() => setActiveSection(section.value)}
            >
              {section.label}
            </button>
          ))}
        </div>
      </aside>
      <div className="admin-main">
        {activeSection === "users" ? (
          <Panel title={t("admin.users")} subtitle={t("admin.usersSubtitle")}>
            <AdminTable
              columns={[t("fields.name"), t("fields.email"), t("admin.role"), t("admin.aiIntegration"), t("admin.content")]}
              rows={data.users.map((item) => [
                item.name,
                item.email,
                item.is_admin ? t("admin.adminRole") : t("admin.userRole"),
                <label className="admin-checkbox-row" key={`ai-${item.id}`}>
                  <input
                    type="checkbox"
                    checked={Boolean(item.ai_enabled)}
                    disabled={submitting === `adminUserAi:${item.id}`}
                    onChange={(event) => onUserAiToggle(item.id, event.target.checked)}
                  />
                  <span>{item.ai_enabled ? t("admin.enabled") : t("admin.disabled")}</span>
                </label>,
                `${item.ingredient_count} / ${item.recipe_count} / ${item.meal_entry_count}`,
              ])}
              emptyLabel={t("admin.empty")}
            />
          </Panel>
        ) : null}

        {activeSection === "ingredients" ? (
          <section className="content-grid">
            <div className="main-column">
              <Panel title={t("admin.ingredients")} subtitle={t("admin.ingredientsSubtitle")}>
                <AdminTable
                  columns={[
                    t("fields.ingredientName"),
                    t("fields.caloriesPer100g"),
                    t("macros.title"),
                    t("fields.email"),
                    t("admin.createdAt"),
                  ]}
                  rows={data.ingredients.map((item) => [
                    item.name,
                    `${item.calories_per_100g} ${t("common.kcal")}`,
                    formatMacroText(item, t, "_per_100g", t("macros.per100gSuffix")),
                    item.user_email || "-",
                    new Date(item.created_at).toLocaleDateString(),
                  ])}
                  emptyLabel={t("ingredients.empty")}
                />
              </Panel>
            </div>
            <aside className="side-column">
              <Panel title={t("admin.addIngredient")} subtitle={t("admin.addIngredientSubtitle")}>
                <form className="stack-form" onSubmit={onIngredientSubmit}>
                  <Field label={t("fields.ingredientName")}>
                    <input
                      placeholder={t("placeholders.ingredientName")}
                      value={ingredientForm.name}
                      onChange={(event) =>
                        setIngredientForm({ ...ingredientForm, name: event.target.value })
                      }
                      required
                    />
                  </Field>
                  <Field label={t("fields.caloriesPer100g")}>
                    <input
                      type="number"
                      min="0"
                      step="0.1"
                      placeholder={t("placeholders.caloriesPer100g")}
                      value={ingredientForm.calories_per_100g}
                      onChange={(event) =>
                        setIngredientForm({
                          ...ingredientForm,
                          calories_per_100g: event.target.value,
                        })
                      }
                      required
                    />
                  </Field>
                  <MacroInputs form={ingredientForm} setForm={setIngredientForm} t={t} />
                  <button type="submit" disabled={submitting === "adminIngredient"}>
                    {submitting === "adminIngredient" ? t("common.saving") : t("ingredients.addButton")}
                  </button>
                </form>
              </Panel>
            </aside>
          </section>
        ) : null}

        {activeSection === "recipes" ? (
          <Panel title={t("admin.recipes")} subtitle={t("admin.recipesSubtitle")}>
            <AdminTable
              columns={[
                t("fields.recipeName"),
                t("fields.email"),
                t("admin.caloriesPer100g"),
                t("macros.title"),
                t("admin.ingredients"),
              ]}
              rows={data.recipes.map((item) => [
                item.name,
                item.user_email || "-",
                Math.round(item.calories_per_100g),
                formatMacroText(item, t),
                item.ingredient_count,
              ])}
              emptyLabel={t("recipes.empty")}
            />
          </Panel>
        ) : null}

        {activeSection === "meals" ? (
          <Panel title={t("admin.meals")} subtitle={t("admin.mealsSubtitle")}>
            <AdminTable
              columns={[
                t("fields.email"),
                t("fields.recipe"),
                t("fields.mealType"),
                t("fields.gramsEaten"),
                t("macros.title"),
              ]}
              rows={data.mealEntries.map((item) => [
                item.user_email || "-",
                item.recipe_name,
                t(`mealTypes.${item.meal_type}`),
                `${Math.round(item.grams_eaten)} ${t("common.gramsShort")}`,
                formatMacroText(item, t),
              ])}
              emptyLabel={t("overview.noMeals")}
            />
          </Panel>
        ) : null}
      </div>
    </section>
  );
}

function AdminTable({ columns, rows, emptyLabel }) {
  if (!rows.length) {
    return <p className="empty-state">{emptyLabel}</p>;
  }

  return (
    <div className="admin-table-wrap">
      <table className="admin-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MealGroups({ dashboard, onEdit, onDelete, t }) {
  return (
    <div className="meal-group-list">
      {dashboard.meals.map((group) => (
        <div className="meal-group" key={group.meal_type}>
          <div className="meal-group-header">
            <div>
              <h3>{labelMealType(group.meal_type, t)}</h3>
              <p>{t("meals.totalCalories", { value: Math.round(group.total_calories) })}</p>
            </div>
            <span>{t("common.items", { count: group.entries.length })}</span>
          </div>
          <div className="entry-list">
            {group.entries.map((entry) => (
              <div className="entry-card" key={entry.id}>
                <div>
                  <strong>{entry.recipe_name}</strong>
                  <p>
                    {entry.note
                      ? t("meals.entrySummaryWithNote", {
                          grams: Math.round(entry.grams_eaten),
                          note: entry.note,
                        })
                      : t("meals.entrySummary", { grams: Math.round(entry.grams_eaten) })}
                  </p>
                  <MacroSummary
                    values={{ protein: entry.protein, carbs: entry.carbs, fat: entry.fat }}
                    t={t}
                  />
                </div>
                <div className="card-actions">
                  <span>{Math.round(entry.calories)} {t("common.kcal")}</span>
                  <div className="inline-actions">
                    <button type="button" className="secondary-button" onClick={() => onEdit(entry)}>
                      {t("common.edit")}
                    </button>
                    <button type="button" className="danger-button" onClick={() => onDelete(entry.id)}>
                      {t("common.delete")}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Panel({ title, subtitle, actionLabel, children }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {actionLabel ? <span className="panel-tag">{actionLabel}</span> : null}
      </div>
      {children}
    </section>
  );
}

function Field({ label, children }) {
  return (
    <label className="field-group">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

function MacroInputs({ form, setForm, t }) {
  return (
    <div className="macro-input-grid">
      {macroFields.map((macro) => (
        <Field key={macro.key} label={t(`fields.${macro.field}`)}>
          <input
            type="number"
            step="0.1"
            min="0"
            placeholder={t(`placeholders.${macro.field}`)}
            value={form[macro.field]}
            onChange={(event) => setForm({ ...form, [macro.field]: event.target.value })}
          />
        </Field>
      ))}
    </div>
  );
}

function MacroSummary({ values, suffix = "", className = "", t }) {
  return (
    <div className={className ? `macro-summary ${className}` : "macro-summary"}>
      {macroFields.map((macro) => (
        <span key={macro.key}>
          {t(macro.labelKey)} {formatMacroValue(values[macro.key])}
          {t("common.gramsShort")}
          {suffix ? ` ${suffix}` : ""}
        </span>
      ))}
    </div>
  );
}

function LanguageSwitcher({ value, options, onChange }) {
  return (
    <div className="language-switcher">
      <select value={value} onChange={onChange}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function labelMealType(mealType, t) {
  const option = mealTypeOptions.find((item) => item.value === mealType);
  return option ? t(option.labelKey) : mealType;
}

function findMatchingIngredients(ingredients, query) {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) {
    return ingredients.slice(0, 50);
  }

  return ingredients
    .filter((ingredient) => normalizeSearchText(ingredient.name).includes(normalizedQuery))
    .slice(0, 50);
}

function normalizeSearchText(value) {
  return value
    .toLocaleLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function buildQuickDates(count) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return Array.from({ length: count }, (_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() + index);

    return {
      date,
      isoDate: toLocalIsoDate(date),
    };
  });
}

function toLocalIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatWeekday(date, language) {
  return new Intl.DateTimeFormat(language, { weekday: "short" }).format(date);
}

function formatDayMonth(date, language) {
  return new Intl.DateTimeFormat(language, { day: "numeric", month: "short" }).format(date);
}

function findMealEntryCalories(mealEntryId, dashboard) {
  if (!dashboard) {
    return 0;
  }
  for (const group of dashboard.meals) {
    const entry = group.entries.find((item) => item.id === mealEntryId);
    if (entry) {
      return entry.calories;
    }
  }
  return 0;
}

function buildIngredientPayload(form) {
  return {
    name: form.name,
    calories_per_100g: Number(form.calories_per_100g),
    protein_per_100g: Number(form.protein_per_100g || 0),
    carbs_per_100g: Number(form.carbs_per_100g || 0),
    fat_per_100g: Number(form.fat_per_100g || 0),
  };
}

function formatMacroText(values, t, suffix = "", suffixLabel = "") {
  return macroFields
    .map((macro) => {
      const value =
        values[`${macro.key}${suffix}`] ??
        values[macro.key] ??
        values[`total_${macro.key}`] ??
        0;
      return `${t(macro.labelKey)} ${formatMacroValue(value)}${t("common.gramsShort")}${suffixLabel ? ` ${suffixLabel}` : ""}`;
    })
    .join(" / ");
}

function formatMacroValue(value) {
  return Math.round((Number(value) || 0) * 10) / 10;
}

export default App;
