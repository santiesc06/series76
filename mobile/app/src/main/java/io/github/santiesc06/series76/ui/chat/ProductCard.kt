package io.github.santiesc06.series76.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AssistChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import io.github.santiesc06.series76.data.api.Product
import io.github.santiesc06.series76.data.api.Spec
import io.github.santiesc06.series76.ui.common.enclosureLabel
import io.github.santiesc06.series76.ui.common.formatSpecValue
import io.github.santiesc06.series76.ui.theme.tabular

/**
 * One product as a card (US-18 AC1): identity, then specs grouped and ordered by the backend.
 * Every value comes from the database through the API; the app never computes a spec.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProductCard(product: Product, modifier: Modifier = Modifier) {
    OutlinedCard(modifier = modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Column {
                Text(
                    product.partNumber,
                    style = MaterialTheme.typography.titleMedium.tabular(),
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "Model ${product.modelCode}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(onClick = {}, label = { Text(enclosureLabel(product.enclosure)) })
                AssistChip(onClick = {}, label = { Text(product.powerSupply.label) })
            }

            product.matchNote?.let { Banner(it, Icons.Filled.Warning, warning = true) }
            if (!product.dataAvailable) {
                Banner(
                    "No electrical data is published for this model.",
                    Icons.Filled.Info,
                    warning = false,
                )
            }

            product.specGroups.forEach { group ->
                Column {
                    Text(
                        group.title,
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Spacer(Modifier.size(4.dp))
                    group.specs.forEachIndexed { index, spec ->
                        if (index > 0) HorizontalDivider()
                        SpecRow(spec, highlighted = spec.key in product.highlight)
                    }
                }
            }

            if (product.certifications.isNotEmpty() || product.hazardousMarkings.isNotEmpty()) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text("Certifications", style = MaterialTheme.typography.labelLarge)
                    if (product.certifications.isNotEmpty()) {
                        Text(
                            product.certifications.joinToString("  ·  "),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    // Marking strings are copied word for word from the datasheet (US-13 AC1).
                    product.hazardousMarkings.forEach {
                        Text(it, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            product.notes.forEach {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    fontStyle = FontStyle.Italic,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun SpecRow(spec: Spec, highlighted: Boolean) {
    val background =
        if (highlighted) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surface
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(background, RoundedCornerShape(4.dp))
            .padding(horizontal = 4.dp, vertical = 6.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            spec.label,
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = if (highlighted) FontWeight.SemiBold else FontWeight.Normal,
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.width(12.dp))
        Column(horizontalAlignment = Alignment.End) {
            spec.values.forEach {
                Text(
                    formatSpecValue(it),
                    style = MaterialTheme.typography.bodyMedium.tabular(),
                    fontWeight = if (highlighted) FontWeight.SemiBold else FontWeight.Normal,
                    textAlign = TextAlign.End,
                )
            }
        }
    }
}

/** Warnings use the error role with an icon and text, never the brand amber alone (M6). */
@Composable
fun Banner(text: String, icon: ImageVector, warning: Boolean, modifier: Modifier = Modifier) {
    val container =
        if (warning) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.surfaceVariant
    val content =
        if (warning) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onSurfaceVariant
    Surface(color = container, contentColor = content, shape = RoundedCornerShape(8.dp), modifier = modifier) {
        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(text, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
