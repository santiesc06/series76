package io.github.santiesc06.series76.ui

import io.github.santiesc06.series76.data.api.SpecValue
import io.github.santiesc06.series76.ui.common.formatRelativeTime
import io.github.santiesc06.series76.ui.common.formatSpecValue
import io.github.santiesc06.series76.ui.common.formatSpecValues
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.OffsetDateTime

/** Numbers are shown exactly like the datasheet (design A3, NFR-01). */
class FormattingTest {

    @Test
    fun `whole numbers get thousands separators and their unit`() {
        assertEquals("4,400 in-lbs", formatSpecValue(SpecValue(4400.0, "in-lbs")))
    }

    @Test
    fun `decimals keep their digits and percent sticks to the number`() {
        assertEquals("4.8 A", formatSpecValue(SpecValue(4.8, "A")))
        assertEquals("30%", formatSpecValue(SpecValue(30.0, "%")))
    }

    @Test
    fun `frequency condition is part of the value`() {
        assertEquals("26 s (60 Hz)", formatSpecValue(SpecValue(26.0, "s", "60 Hz")))
    }

    @Test
    fun `missing values show a dash, never zero`() { // US-12 AC2
        assertEquals("—", formatSpecValue(SpecValue(null, "W")))
        assertEquals("—", formatSpecValues(emptyList()))
    }

    @Test
    fun `relative time for the conversation list`() {
        val now = OffsetDateTime.parse("2026-11-07T15:00:00Z")
        assertEquals("Just now", formatRelativeTime("2026-11-07T14:59:40Z", now))
        assertEquals("12 min ago", formatRelativeTime("2026-11-07T14:48:00Z", now))
        assertEquals("3 h ago", formatRelativeTime("2026-11-07T12:00:00+00:00", now))
        assertEquals("", formatRelativeTime("not a date", now))
    }
}
