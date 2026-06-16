package sh.igniteember.embercode

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test
import sh.igniteember.embercode.actions.EmberHostEvents

/**
 * Tests the inline JSON escaper in [EmberHostEvents].
 *
 * Why hand-rolled instead of a JSON library: this is the ONLY string
 * the plugin emits into the JCEF webview as raw JS, and pulling in a
 * full JSON dep just to escape it would bloat the plugin jar. The
 * tradeoff is paying down with tests on the corner cases that bite —
 * quotes, backslashes, control characters, newlines.
 */
class EmberHostEventsTest {
    @Test
    fun `unchanged when input has no escape-needing chars`() {
        assertEquals(
            "hello world",
            EmberHostEvents.jsonEscape("hello world"),
        )
    }

    @Test
    fun `doubles backslashes`() {
        assertEquals(
            "a\\\\b",
            EmberHostEvents.jsonEscape("a\\b"),
        )
    }

    @Test
    fun `escapes embedded double quotes`() {
        assertEquals(
            "a\\\"b",
            EmberHostEvents.jsonEscape("a\"b"),
        )
    }

    @Test
    fun `escapes newlines, carriage returns, tabs`() {
        assertEquals(
            "a\\nb\\rc\\td",
            EmberHostEvents.jsonEscape("a\nb\rc\td"),
        )
    }

    @Test
    fun `escapes other control characters as unicode escapes`() {
        // Form feed (0x0C) is a control char that's not in the
        // shortcut set; should become a  sequence.
        assertEquals(
            "a\\u000cb",
            EmberHostEvents.jsonEscape("ab"),
        )
    }

    @Test
    fun `leaves Unicode letters intact (only control chars + special escapes are touched)`() {
        assertEquals(
            "café — flame",
            EmberHostEvents.jsonEscape("café — flame"),
        )
    }
}
