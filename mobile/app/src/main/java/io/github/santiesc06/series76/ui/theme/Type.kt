package io.github.santiesc06.series76.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily

val AppTypography = Typography()

/**
 * Tabular figures: every digit has the same width, so values line up in spec rows and in the
 * comparison table (design M6).
 */
fun TextStyle.tabular(): TextStyle = copy(fontFeatureSettings = "tnum")

val CodeTextStyle = TextStyle(fontFamily = FontFamily.Monospace)
