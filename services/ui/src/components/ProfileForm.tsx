import { useState } from "react";
import type { Profile } from "../api";

const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function ProfileForm({ initial, onSave }: { initial?: Profile | null; onSave: (p: Profile) => Promise<Profile | void> }) {
  const [skills, setSkills] = useState(initial?.skills.join(", ") ?? "");
  const [interests, setInterests] = useState(initial?.interests.join(", ") ?? "");
  const [hours, setHours] = useState(String(initial?.hours_per_week ?? 10));
  const [weeks, setWeeks] = useState(String(initial?.weeks_available ?? 12));
  const [team, setTeam] = useState(String(initial?.team_size ?? 1));
  const [compute, setCompute] = useState<Profile["compute"]>(initial?.compute ?? "laptop");
  const [goal, setGoal] = useState<Profile["goal"]>(initial?.goal ?? "portfolio");
  const [errors, setErrors] = useState<string[]>([]);
  const [version, setVersion] = useState<number | undefined>(initial?.profile_version);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    const errs: string[] = [];
    const h = Number(hours), w = Number(weeks), t = Number(team);
    if (!split(skills).length) errs.push("Add at least one skill");
    if (!(h >= 0 && h <= 80)) errs.push("Hours per week must be 0-80");
    if (!(Number.isInteger(w) && w >= 1 && w <= 52)) errs.push("Weeks must be 1-52");
    if (!(Number.isInteger(t) && t >= 1 && t <= 6)) errs.push("Team size must be 1-6");
    setErrors(errs);
    if (errs.length) return;
    const saved = await onSave({ skills: split(skills), interests: split(interests), hours_per_week: h, weeks_available: w, team_size: t, compute, goal });
    if (saved && saved.profile_version) setVersion(saved.profile_version);
  };
  const field = "border p-2 w-full";
  return (
    <form onSubmit={save} className="space-y-2 bg-white p-4 rounded shadow" aria-label="profile">
      <div className="flex justify-between"><h2 className="font-semibold">Your profile</h2>{version && <span className="text-xs bg-slate-200 px-2 rounded">profile v{version}</span>}</div>
      <label className="block">Skills (comma separated)<input aria-label="skills" className={field} value={skills} onChange={(e) => setSkills(e.target.value)} /></label>
      <label className="block">Interests<input aria-label="interests" className={field} value={interests} onChange={(e) => setInterests(e.target.value)} /></label>
      <div className="grid grid-cols-3 gap-2">
        <label>Hours/week<input aria-label="hours" className={field} value={hours} onChange={(e) => setHours(e.target.value)} /></label>
        <label>Weeks<input aria-label="weeks" className={field} value={weeks} onChange={(e) => setWeeks(e.target.value)} /></label>
        <label>Team size<input aria-label="team" className={field} value={team} onChange={(e) => setTeam(e.target.value)} /></label>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label>Compute<select aria-label="compute" className={field} value={compute} onChange={(e) => setCompute(e.target.value as Profile["compute"])}>
          <option value="laptop">laptop</option><option value="free_gpu">free GPU</option><option value="paid">paid</option></select></label>
        <label>Goal<select aria-label="goal" className={field} value={goal} onChange={(e) => setGoal(e.target.value as Profile["goal"])}>
          <option value="startup">startup</option><option value="portfolio">portfolio</option><option value="course_project">course project</option></select></label>
      </div>
      {errors.map((e) => <p role="alert" key={e} className="text-red-600 text-sm">{e}</p>)}
      <button className="bg-indigo-600 text-white px-4 py-1 rounded">Save</button>
    </form>
  );
}
