package agent.memory;

import br.unicamp.cst.representation.idea.Idea;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/**
 * The content of SensoryBuffer (cap4 4.2): a short history of recent SensoryMO Ideas, newest last.
 * Written only by the Sensory codelet; cleared at the start of each episode, so it never mixes
 * perceptions from two episodes.
 */
public final class SensoryBuffer {

    private final int capacity;
    private final ArrayDeque<Idea> items = new ArrayDeque<>();

    public SensoryBuffer(int capacity) {
        this.capacity = capacity;
    }

    public void add(Idea observation) {
        items.addLast(observation);
        while (items.size() > capacity) {
            items.removeFirst();
        }
    }

    public void clear() {
        items.clear();
    }

    public int size() {
        return items.size();
    }

    public List<Idea> recent() {
        return new ArrayList<>(items);
    }
}
