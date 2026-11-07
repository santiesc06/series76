package io.github.santiesc06.series76.ui.common

import io.github.santiesc06.series76.data.api.SpecValue
import java.text.NumberFormat
import java.time.Duration
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale

// Spec numbers are shown exactly as the source tables write them ("4,400"), whatever the device
// locale, so they can be checked against the datasheet (NFR-01).
private val numberFormat = NumberFormat.getNumberInstance(Locale.US).apply {
    maximumFractionDigits = 2
}

fun formatNumber(value: Double): String = numberFormat.format(value)

/** "4,400 in-lbs", "26 s (60 Hz)", "—" for a missing value (US-12 AC2). */
fun formatSpecValue(v: SpecValue): String {
    val number = v.value?.let(::formatNumber) ?: return "—"
    val unit = if (v.unit == "%") "%" else " ${v.unit}"
    val condition = v.condition?.let { " ($it)" } ?: ""
    return "$number$unit$condition"
}

fun formatSpecValues(values: List<SpecValue>): String =
    if (values.isEmpty()) "—" else values.joinToString("  ·  ", transform = ::formatSpecValue)

/** "Just now", "12 min ago", "3 h ago", or a short date for older conversations. */
fun formatRelativeTime(iso: String, now: OffsetDateTime = OffsetDateTime.now()): String {
    val time = runCatching { OffsetDateTime.parse(iso) }.getOrNull() ?: return ""
    val elapsed = Duration.between(time, now)
    return when {
        elapsed.toMinutes() < 1 -> "Just now"
        elapsed.toMinutes() < 60 -> "${elapsed.toMinutes()} min ago"
        elapsed.toHours() < 24 -> "${elapsed.toHours()} h ago"
        else -> time.atZoneSameInstant(ZoneId.systemDefault())
            .format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM))
    }
}

fun enclosureLabel(enclosure: String): String =
    enclosure.replaceFirstChar { it.titlecase(Locale.US) }
