"use client";

import {
  Archive,
  FolderPlus,
  LoaderCircle,
  Pencil,
  Plus,
  Tags,
  Trash2,
  X,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { SelectField } from "@/components/select-field";
import { CategoryDetail } from "@/components/category-detail";
import { apiFetch } from "@/lib/api";
import { Category, Tag } from "@/lib/finance";

type Group = {
  id: string;
  name: string;
  is_income: boolean;
  sort_order: number;
  category_count: number;
};

const BUCKETS = [
  { value: "fixed", label: "Fixed — same every month" },
  { value: "flex", label: "Flex — varies month to month" },
  { value: "non_monthly", label: "Non-monthly — periodic" },
  { value: "goal", label: "Goal — saving toward something" },
];

const SWATCHES = [
  "#bd5b51",
  "#c86b5e",
  "#d47768",
  "#d99049",
  "#e3a158",
  "#d77f35",
  "#4f8062",
  "#699476",
  "#5f8f9a",
  "#6d7fa8",
  "#8b6ea6",
  "#7f8b81",
];

function CategoryDialog({
  category,
  groups,
  onClose,
  onSaved,
}: {
  category?: Category;
  groups: Group[];
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [name, setName] = useState(category?.name ?? "");
  const [groupId, setGroupId] = useState(
    category?.group_id ?? groups[0]?.id ?? "",
  );
  const [color, setColor] = useState(category?.color ?? SWATCHES[6]);
  const [bucket, setBucket] = useState<string>(
    category?.flex_bucket ?? "flex",
  );
  const [excluded, setExcluded] = useState(
    category?.excluded_from_budget ?? false,
  );
  /**
   * Whether this category's spending counts against the previous month's plan.
   *
   * Rent is the case. It is due on the 1st, paid out of last month's pay, and
   * posts in the new month — so counted where it posts, the new month looks
   * funded while nothing says to set the next one aside. Setting it here
   * rather than on each transaction is what makes it stop being a monthly
   * chore.
   */
  const [monthOffset, setMonthOffset] = useState(
    String(category?.budget_month_offset ?? 0),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const body = {
      name: name.trim(),
      group_id: groupId,
      color,
      flex_bucket: bucket,
      excluded_from_budget: excluded,
      budget_month_offset: Number(monthOffset),
    };
    try {
      if (category) {
        await apiFetch(`/categories/${category.id}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        onSaved(`${body.name} updated.`);
      } else {
        await apiFetch("/categories", {
          method: "POST",
          body: JSON.stringify(body),
        });
        onSaved(`${body.name} created.`);
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not save the category",
      );
      setSaving(false);
    }
  }

  return (
    <div className="dialog-layer">
      <button
        aria-label="Close dialog"
        className="dialog-backdrop"
        onClick={onClose}
        type="button"
      />
      <section
        aria-label={category ? "Edit category" : "New category"}
        aria-modal="true"
        className="account-dialog rule-dialog"
        role="dialog"
      >
        <div className="dialog-header">
          <div>
            <p className="eyebrow">{category ? "Edit" : "New"} category</p>
            <h2>{category ? category.name : "Add a category"}</h2>
          </div>
          <button
            aria-label="Close"
            className="dialog-close"
            onClick={onClose}
            type="button"
          >
            <X size={16} />
          </button>
        </div>
        <form className="dialog-form" onSubmit={save}>
          <div className="field">
            <span>Name</span>
            <input
              autoFocus
              className="form-control"
              maxLength={100}
              onChange={(event) => setName(event.target.value)}
              placeholder="Coffee"
              required
              type="text"
              value={name}
            />
          </div>
          <div className="field-grid">
            <div className="field">
              <span>Group</span>
              <SelectField
                ariaLabel="Category group"
                onChange={setGroupId}
                options={groups.map((group) => ({
                  value: group.id,
                  label: group.name,
                  hint: group.is_income ? "Income" : undefined,
                }))}
                value={groupId}
              />
            </div>
            <div className="field">
              <span>Budget behaviour</span>
              <SelectField
                ariaLabel="Budget behaviour"
                onChange={setBucket}
                options={BUCKETS}
                value={bucket}
              />
            </div>
          </div>
          <div className="field">
            <span>Colour</span>
            <div className="swatch-row">
              {SWATCHES.map((option) => (
                <button
                  aria-label={`Colour ${option}`}
                  aria-pressed={color === option}
                  className={`swatch ${color === option ? "active" : ""}`}
                  key={option}
                  onClick={() => setColor(option)}
                  style={{ backgroundColor: option }}
                  type="button"
                />
              ))}
            </div>
          </div>
          {/* The category-wide counterpart of the per-transaction exclusion in
              the transaction dialog. Ticking every future transaction by hand
              was the only way to do this before. */}
          {/* Applied when the budget is read, not written into each row, so
              changing it corrects the months already recorded rather than only
              what happens next. */}
          <label className="field full">
            <span>Which month&apos;s plan this counts against</span>
            <select
              onChange={(event) => setMonthOffset(event.target.value)}
              value={monthOffset}
            >
              <option value="0">The month it posted in</option>
              <option value="-1">The month before it posted</option>
              <option value="1">The month after it posted</option>
            </select>
            <small className="field-help">
              {monthOffset === "-1"
                ? "Rent due on the 1st comes out of last month's pay, so it counts there — and this month's plan keeps showing what you still need to set aside. Reports are unaffected."
                : monthOffset === "1"
                  ? "For something paid in advance of the month it belongs to."
                  : "The usual answer. Change it for a bill that is paid out of the previous month's pay, like rent due on the 1st."}
            </small>
          </label>
          <label className="toggle-row full">
            <input
              checked={excluded}
              onChange={(event) => setExcluded(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>Never count this category</strong>
              <small>
                Kept out of budgets, spending totals and reports — for money
                that passes through without being yours to spend, like
                reimbursed expenses or someone else&apos;s share. The
                transactions stay where they are and stay visible.
              </small>
            </span>
          </label>
          {error && (
            <p className="negative" role="alert">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <button className="ghost-button" onClick={onClose} type="button">
              Cancel
            </button>
            <button className="primary-button" disabled={saving} type="submit">
              {saving ? "Saving…" : category ? "Save category" : "Create"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

function TagDialog({
  onClose,
  onDeleted,
  onSaved,
  tag,
}: {
  onClose: () => void;
  onDeleted: (message: string) => void;
  onSaved: (message: string) => void;
  tag?: Tag;
}) {
  const [name, setName] = useState(tag?.name ?? "");
  const [color, setColor] = useState(tag?.color ?? SWATCHES[5]);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const body = { name: name.trim(), color };
    try {
      await apiFetch(tag ? `/categories/tags/${tag.id}` : "/categories/tags", {
        method: tag ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
      onSaved(`${body.name} ${tag ? "updated" : "created"}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save tag");
      setSaving(false);
    }
  }

  async function remove() {
    if (!tag) return;
    setSaving(true);
    setError("");
    try {
      await apiFetch<void>(`/categories/tags/${tag.id}`, { method: "DELETE" });
      onDeleted(`${tag.name} deleted. It was removed from tagged transactions.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete tag");
      setSaving(false);
    }
  }

  return (
    <div className="dialog-layer">
      <button aria-label="Close dialog" className="dialog-backdrop" onClick={onClose} type="button" />
      <section aria-label={tag ? "Edit tag" : "New tag"} aria-modal="true" className="account-dialog rule-dialog" role="dialog">
        <div className="dialog-header">
          <div>
            <p className="eyebrow">{tag ? "Edit" : "New"} tag</p>
            <h2>{tag ? tag.name : "Add a reusable label"}</h2>
            <p>Tags add context across categories, accounts, and reporting periods.</p>
          </div>
          <button aria-label="Close" className="dialog-close" onClick={onClose} type="button"><X size={16} /></button>
        </div>
        <form className="dialog-form" onSubmit={save}>
          <label className="field">
            <span>Name</span>
            <input autoFocus className="form-control" maxLength={80} onChange={(event) => setName(event.target.value)} placeholder="Wedding" required value={name} />
          </label>
          <div className="field">
            <span>Colour</span>
            <div className="swatch-row">
              {SWATCHES.map((option) => (
                <button aria-label={`Colour ${option}`} aria-pressed={color === option} className={`swatch ${color === option ? "active" : ""}`} key={option} onClick={() => setColor(option)} style={{ backgroundColor: option }} type="button" />
              ))}
            </div>
          </div>
          {error && <p className="negative" role="alert">{error}</p>}
          {tag && (
            <div className="account-danger-zone">
              {confirmDelete ? (
                <div>
                  <span><strong>Delete this tag?</strong><small>Transaction amounts and categories are unaffected.</small></span>
                  <button className="danger-button" disabled={saving} onClick={() => void remove()} type="button"><Trash2 size={13} /> Delete</button>
                  <button className="text-button" onClick={() => setConfirmDelete(false)} type="button">Cancel</button>
                </div>
              ) : (
                <button className="danger-text-button" onClick={() => setConfirmDelete(true)} type="button"><Trash2 size={13} /> Delete tag</button>
              )}
            </div>
          )}
          <div className="dialog-actions">
            <button className="ghost-button" onClick={onClose} type="button">Cancel</button>
            <button className="primary-button" disabled={saving || !name.trim()} type="submit">{saving ? "Saving…" : tag ? "Save tag" : "Create tag"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

export function CategoriesManager() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [role, setRole] = useState<"owner" | "member" | "viewer" | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [inspecting, setInspecting] = useState<Category | null>(null);
  const [editing, setEditing] = useState<Category | null>(null);
  const [creating, setCreating] = useState(false);
  const [editingTag, setEditingTag] = useState<Tag | null>(null);
  const [creatingTag, setCreatingTag] = useState(false);
  const [newGroup, setNewGroup] = useState("");
  const [busy, setBusy] = useState("");

  async function load() {
    try {
      const [categoryResult, groupResult, tagResult] = await Promise.all([
        apiFetch<Category[]>("/categories"),
        apiFetch<Group[]>("/categories/groups"),
        apiFetch<Tag[]>("/categories/tags"),
      ]);
      setCategories(categoryResult);
      setGroups(groupResult);
      setTags(tagResult);
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load categories",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ role: "owner" | "member" | "viewer" }>("/auth/me")
      .then((session) => {
        if (!cancelled) setRole(session.role);
      })
      .catch(() => {});
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const canEdit = role !== null && role !== "viewer";

  const byGroup = useMemo(() => {
    const map = new Map<string, Category[]>();
    for (const category of categories) {
      map.set(category.group_id, [
        ...(map.get(category.group_id) ?? []),
        category,
      ]);
    }
    return map;
  }, [categories]);

  async function addGroup(event: FormEvent) {
    event.preventDefault();
    if (!newGroup.trim()) return;
    setBusy("group");
    try {
      await apiFetch("/categories/groups", {
        method: "POST",
        body: JSON.stringify({ name: newGroup.trim(), is_income: false }),
      });
      setNewGroup("");
      setToast("Group created.");
      await load();
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not create the group",
      );
    } finally {
      setBusy("");
    }
  }

  async function archive(category: Category) {
    setBusy(category.id);
    try {
      await apiFetch<void>(`/categories/${category.id}`, { method: "DELETE" });
      setToast(
        `${category.name} removed. Past transactions keep their history.`,
      );
      await load();
    } catch (reason) {
      setToast(
        reason instanceof Error ? reason.message : "Could not remove it",
      );
    } finally {
      setBusy("");
    }
  }

  if (loading) {
    return (
      <div className="account-loading">
        <LoaderCircle className="spin" size={21} />
        Loading categories…
      </div>
    );
  }

  return (
    <>
      {toast && <div className="toast">{toast}</div>}
      <div className="page-heading">
        <div>
          <p className="eyebrow">Organization</p>
          <h1>Your categories, your words.</h1>
          <p className="subtle">
            Group spending however you actually think about it, then layer tags
            across categories for projects, people, and special events.
          </p>
        </div>
        {canEdit && (
          <button
            className="primary-button"
            disabled={!groups.length}
            onClick={() => setCreating(true)}
            type="button"
          >
            <Plus size={15} /> New category
          </button>
        )}
      </div>

      {error && <div className="page-error">{error}</div>}

      <div className="category-groups">
        {groups.map((group) => (
          <section className="panel category-group" key={group.id}>
            <div className="category-group-heading">
              <div>
                <h2>{group.name}</h2>
                <small>
                  {group.is_income ? "Income" : "Spending"} ·{" "}
                  {byGroup.get(group.id)?.length ?? 0} categories
                </small>
              </div>
            </div>
            <div className="category-chips">
              {(byGroup.get(group.id) ?? []).map((category) => (
                <div className="category-item" key={category.id}>
                  <span
                    aria-hidden="true"
                    className="category-dot"
                    style={{ backgroundColor: category.color }}
                  />
                  {/* The name opens the detail rather than the editor: "why
                      is Dining $900" is asked far more often than "rename
                      Dining", and it had no answer short of filtering the
                      transaction list by hand. */}
                  <button
                    className="category-name-button"
                    onClick={() => setInspecting(category)}
                    type="button"
                  >
                    <strong>{category.name}</strong>
                  </button>
                  {canEdit && (
                    <span className="category-item-actions">
                      <button
                        aria-label={`Edit ${category.name}`}
                        className="icon-button"
                        onClick={() => setEditing(category)}
                        type="button"
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        aria-label={`Remove ${category.name}`}
                        className="icon-button"
                        disabled={busy === category.id}
                        onClick={() => void archive(category)}
                        type="button"
                      >
                        <Archive size={12} />
                      </button>
                    </span>
                  )}
                </div>
              ))}
              {!(byGroup.get(group.id) ?? []).length && (
                <p className="subtle">No categories in this group yet.</p>
              )}
            </div>
          </section>
        ))}
      </div>

      <section className="panel tag-workspace">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Across every category</p>
            <h2>Transaction tags</h2>
            <p className="subtle">Track a wedding, vacation, reimbursement, person, or tax purpose without changing the budget category.</p>
          </div>
          {canEdit && (
            <button className="ghost-button" onClick={() => setCreatingTag(true)} type="button"><Tags size={14} /> New tag</button>
          )}
        </div>
        {tags.length ? (
          <div className="tag-library">
            {tags.map((tag) => (
              <button className="tag-library-item" disabled={!canEdit} key={tag.id} onClick={() => setEditingTag(tag)} type="button">
                <i style={{ backgroundColor: tag.color }} />
                <strong>{tag.name}</strong>
                {canEdit && <Pencil size={12} />}
              </button>
            ))}
          </div>
        ) : (
          <div className="tag-empty"><Tags size={19} /><strong>No tags yet</strong><small>Create a label once, then attach it from any transaction.</small></div>
        )}
      </section>

      {canEdit && (
        <form className="new-group-row" onSubmit={addGroup}>
          <FolderPlus size={15} />
          <input
            aria-label="New group name"
            className="form-control"
            maxLength={100}
            onChange={(event) => setNewGroup(event.target.value)}
            placeholder="Add a group — Travel, Kids, Pets…"
            value={newGroup}
          />
          <button
            className="ghost-button"
            disabled={busy === "group" || !newGroup.trim()}
            type="submit"
          >
            Add group
          </button>
        </form>
      )}

      {inspecting && (
        <CategoryDetail
          categoryId={inspecting.id}
          onClose={() => setInspecting(null)}
        />
      )}

      {(creating || editing) && (
        <CategoryDialog
          category={editing ?? undefined}
          groups={groups}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={(message) => {
            setCreating(false);
            setEditing(null);
            setToast(message);
            void load();
          }}
        />
      )}
      {(creatingTag || editingTag) && (
        <TagDialog
          onClose={() => {
            setCreatingTag(false);
            setEditingTag(null);
          }}
          onDeleted={(message) => {
            setCreatingTag(false);
            setEditingTag(null);
            setToast(message);
            void load();
          }}
          onSaved={(message) => {
            setCreatingTag(false);
            setEditingTag(null);
            setToast(message);
            void load();
          }}
          tag={editingTag ?? undefined}
        />
      )}
    </>
  );
}
