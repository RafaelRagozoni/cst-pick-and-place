package agent.memory;

import agent.credit.CreditTable;

import java.util.Set;

/**
 * The content of CreditMO: the credit table, and which habits' credit changed on {@code cycle}, so
 * the HabitLearner copies only those into the HabitPool.
 */
public record CreditUpdate(CreditTable table, Set<String> changed, long cycle) {
}
