import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

/**
 * BRG-02/BRG-03 acceptance from the Java side: drive the simulator over the bridge and measure the
 * per-cycle round trip with a JVM in the loop.
 *
 * <p>Deliberately contains no task logic -- it sends joint-velocity records and reads observations,
 * which is exactly the interface a CST MotorHEC/sensory-HEC pair will use.
 *
 * <pre>
 *   javac -cp "lib/*" -d out BridgeClient.java BridgeSmokeTest.java
 *   java  -cp "lib/*:out" BridgeSmokeTest [port]
 * </pre>
 */
public class BridgeSmokeTest {

    public static void main(String[] args) {
        int port = args.length > 0 ? Integer.parseInt(args[0]) : 5555;
        boolean ok = true;

        try (BridgeClient c = new BridgeClient("127.0.0.1", port, 20000)) {
            JsonObject info = c.info();
            int nPrim = info.getAsJsonArray("primitives").size();
            String engine = info.getAsJsonObject("physics").get("engineName").getAsString();
            System.out.printf("  connected: protocol %d, %d primitives, physics %s%n",
                    info.get("protocol").getAsInt(), nPrim, engine);
            ok &= check("14 primitives offered", nPrim == 14);
            ok &= check("goal steps advertised",
                    info.getAsJsonArray("goalSteps").size() == 4);

            JsonObject r = c.reset(1, 0);
            JsonObject obs = r.getAsJsonObject("obs");
            double width = obs.getAsJsonObject("innerSense").getAsJsonObject("gripper")
                    .get("width").getAsDouble();
            ok &= check("reset returns an observation",
                    obs.has("innerSense") && obs.has("vision"));
            ok &= check("gripper open after reset", width > 0.05);
            ok &= check("goal starts at reach",
                    r.getAsJsonObject("goal").get("current").getAsString().equals("reach"));

            double t0 = obs.get("t").getAsDouble();
            JsonObject s = c.step(new JsonArray());
            ok &= check("one step advances the clock once",
                    Math.abs((s.getAsJsonObject("obs").get("t").getAsDouble() - t0) - 0.05) < 1e-6);

            // Drive joints and watch the arm actually move.
            double[] before = joints(s.getAsJsonObject("obs"));
            long[] lat = new long[200];
            for (int i = 0; i < lat.length; i++) {
                JsonArray recs = new JsonArray();
                recs.add(BridgeClient.move(1, i < 120 ? 0.4 : -0.4));
                long t = System.nanoTime();
                s = c.step(recs);
                lat[i] = System.nanoTime() - t;
            }
            double[] after = joints(s.getAsJsonObject("obs"));
            double moved = 0;
            for (int i = 0; i < 6; i++) {
                moved = Math.max(moved, Math.abs(after[i] - before[i]));
            }
            ok &= check(String.format("commanded joint moved (%.3f rad)", moved), moved > 0.05);

            // Gripper, through the environment's own rule -- the agent only opens and closes it.
            JsonArray close = new JsonArray();
            close.add(BridgeClient.grab(false));
            for (int i = 0; i < 60; i++) {
                s = c.step(close);
            }
            double closedWidth = s.getAsJsonObject("obs").getAsJsonObject("innerSense")
                    .getAsJsonObject("gripper").get("width").getAsDouble();
            ok &= check(String.format("gripper closes on command (%.4f m)", closedWidth),
                    closedWidth < 0.02);

            java.util.Arrays.sort(lat);
            System.out.printf("  per-cycle round trip, JVM in the loop: mean %.2f ms, median %.2f, "
                            + "p95 %.2f%n",
                    avg(lat) / 1e6, lat[lat.length / 2] / 1e6, lat[(int) (lat.length * 0.95)] / 1e6);

            c.shutdown();
        } catch (Exception e) {
            System.out.println("  EXCEPTION: " + e);
            ok = false;
        }

        System.out.println();
        System.out.println("JAVA BRIDGE ACCEPTANCE: " + (ok ? "PASS" : "FAIL"));
        System.exit(ok ? 0 : 1);
    }

    private static double avg(long[] v) {
        double s = 0;
        for (long x : v) {
            s += x;
        }
        return s / v.length;
    }

    private static double[] joints(JsonObject obs) {
        JsonArray js = obs.getAsJsonObject("innerSense").getAsJsonArray("joints");
        double[] q = new double[js.size()];
        for (int i = 0; i < q.length; i++) {
            q[i] = js.get(i).getAsJsonObject().get("pos").getAsDouble();
        }
        return q;
    }

    private static boolean check(String name, boolean good) {
        System.out.printf("  %-42s %s%n", name, good ? "PASS" : "FAIL");
        return good;
    }
}
