package agent.habit;

import agent.credit.CreditSnapshot;
import br.unicamp.cst.representation.idea.Idea;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.List;
import java.util.TreeMap;

/**
 * A habit as cap4 4.4.1 defines it: an Idea holding an ordered list of command records, executed by
 * the PlanTracker and the Motor rather than through {@code Habit.exec}.
 *
 * <pre>
 *   Idea &lt;habit id&gt;
 *     origin    primitive | mutation | parallel | macro
 *     parents   space-separated parent ids ("" for a primitive)
 *     commands  r000, r001, ...   one Command Idea each (see Command.toIdea)
 *     credit    value = CreditSnapshot, copied in by the HabitLearner (cap4 4.3.4)
 *
 *   and a macro (vault spec MAC-01) also has
 *     initiation    the context (goal|state bin) its stretch started in: the only one it is
 *                   chosen in
 *     stretchSteps  how many executed steps the stretch it was built from had
 *     retired       true once a shorter stretch from the same context replaced it: it stays in the
 *                   pool with its credit, but is never chosen again
 * </pre>
 *
 * Command children are zero-padded because Idea.add keeps its children sorted by name: "r10" would
 * otherwise sort before "r2". The order is a property of the habit, so it is not left to that.
 */
public final class HabitIdeas {

    public static final String PRIMITIVE = "primitive";
    public static final String MUTATION = "mutation";
    public static final String PARALLEL = "parallel";
    public static final String MACRO = "macro";

    private HabitIdeas() {
    }

    public static Idea create(String id, String origin, List<String> parents, List<Command> commands) {
        Idea h = new Idea(id, null, 0);
        h.add(new Idea("origin", origin, 1));
        h.add(new Idea("parents", String.join(" ", parents), 1));
        Idea cmds = new Idea("commands", null, 0);
        for (int i = 0; i < commands.size(); i++) {
            cmds.add(commands.get(i).toIdea(String.format("r%03d", i)));
        }
        h.add(cmds);
        h.add(new Idea("credit", CreditSnapshot.EMPTY, 1));
        return h;
    }

    /** The primary repertoire as the bridge's {@code info} reply lists it. */
    public static List<Idea> fromBridgeInfo(JsonObject info) {
        List<Idea> out = new ArrayList<>();
        for (JsonElement e : info.getAsJsonArray("primitives")) {
            JsonObject p = e.getAsJsonObject();
            List<Command> recs = new ArrayList<>();
            for (JsonElement r : p.getAsJsonArray("records")) {
                recs.add(Command.fromJson(r.getAsJsonObject()));
            }
            out.add(create(p.get("id").getAsString(), PRIMITIVE, List.of(), recs));
        }
        return out;
    }

    /** A macro (vault spec MAC-01): built from {@code stretchSteps} steps that started in {@code initiation}. */
    public static Idea createMacro(String id, List<String> parents, List<Command> commands,
                                   String initiation, int stretchSteps) {
        Idea macro = create(id, MACRO, parents, commands);
        macro.add(new Idea("initiation", initiation, 1));
        macro.add(new Idea("stretchSteps", stretchSteps, 1));
        macro.add(new Idea("retired", false, 1));
        return macro;
    }

    public static boolean isMacro(Idea habit) {
        return MACRO.equals(origin(habit));
    }

    /** The context a macro may be chosen in; null for any other habit, which may be chosen anywhere. */
    public static String initiation(Idea habit) {
        Idea initiation = habit.get("initiation");
        return initiation == null ? null : (String) initiation.getValue();
    }

    public static int stretchSteps(Idea habit) {
        return ((Number) habit.get("stretchSteps").getValue()).intValue();
    }

    public static boolean isRetired(Idea habit) {
        Idea retired = habit.get("retired");
        return retired != null && (Boolean) retired.getValue();
    }

    /** Only the HabitLearner calls this: it is the single writer of the HabitPool. */
    public static void retire(Idea macro) {
        macro.get("retired").setValue(true);
    }

    public static List<String> parents(Idea habit) {
        String parents = (String) habit.get("parents").getValue();
        return parents.isEmpty() ? List.of() : List.of(parents.split(" "));
    }

    public static String id(Idea habit) {
        return habit.getName();
    }

    public static String origin(Idea habit) {
        return (String) habit.get("origin").getValue();
    }

    public static List<Command> commands(Idea habit) {
        List<Command> out = new ArrayList<>();
        for (Idea r : habit.get("commands").getL()) {
            out.add(Command.fromIdea(r));
        }
        return out;
    }

    /** The commands grouped into steps: records sharing a step index, in increasing step order. */
    public static List<List<Command>> steps(Idea habit) {
        TreeMap<Integer, List<Command>> by = new TreeMap<>();
        for (Command c : commands(habit)) {
            by.computeIfAbsent(c.step(), k -> new ArrayList<>()).add(c);
        }
        return new ArrayList<>(by.values());
    }

    public static CreditSnapshot credit(Idea habit) {
        return (CreditSnapshot) habit.get("credit").getValue();
    }

    /** Only the HabitLearner calls this: it is the single writer of the HabitPool. */
    public static void setCredit(Idea habit, CreditSnapshot snapshot) {
        habit.get("credit").setValue(snapshot);
    }

    public static JsonArray toJson(List<Command> commands) {
        JsonArray a = new JsonArray();
        for (Command c : commands) {
            a.add(c.toJson());
        }
        return a;
    }
}
