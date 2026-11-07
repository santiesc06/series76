package io.github.santiesc06.series76.ui.chat

import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.github.santiesc06.series76.data.api.Product
import io.github.santiesc06.series76.data.api.Spec
import io.github.santiesc06.series76.ui.common.enclosureLabel
import io.github.santiesc06.series76.ui.common.formatSpecValue
import io.github.santiesc06.series76.ui.theme.tabular

private val LabelWidth = 132.dp
private val ColumnWidth = 160.dp

private sealed interface TableRow {
    data class Section(val title: String) : TableRow
    data class Values(val label: String, val cells: List<List<String>>) : TableRow
}

/**
 * Side-by-side comparison (US-12): the same spec rows for every product, built from the same
 * spec groups as the cards. A spec a product does not have shows "—", never 0 (US-12 AC2).
 */
@Composable
fun ComparisonTable(products: List<Product>, modifier: Modifier = Modifier) {
    val rows = buildRows(products)
    Column(
        modifier
            .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(12.dp))
            .horizontalScroll(rememberScrollState())
            .padding(vertical = 8.dp),
    ) {
        Row(Modifier.padding(horizontal = 12.dp)) {
            Cell("", LabelWidth)
            products.forEach {
                Cell(it.partNumber, ColumnWidth, bold = true)
            }
        }
        rows.forEach { row ->
            when (row) {
                is TableRow.Section -> {
                    HorizontalDivider(Modifier.padding(top = 8.dp))
                    Text(
                        row.title,
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
                is TableRow.Values -> Row(Modifier.padding(horizontal = 12.dp, vertical = 4.dp)) {
                    Cell(row.label, LabelWidth)
                    row.cells.forEach { lines -> Cell(lines.joinToString("\n"), ColumnWidth) }
                }
            }
        }
    }
}

@Composable
private fun Cell(text: String, width: Dp, bold: Boolean = false) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium.tabular(),
        fontWeight = if (bold) FontWeight.SemiBold else FontWeight.Normal,
        modifier = Modifier.width(width).padding(end = 8.dp),
    )
}

private fun buildRows(products: List<Product>): List<TableRow> {
    val rows = mutableListOf<TableRow>(
        TableRow.Section("General"),
        TableRow.Values("Enclosure", products.map { listOf(enclosureLabel(it.enclosure)) }),
        TableRow.Values("Power supply", products.map { listOf(it.powerSupply.label) }),
        TableRow.Values(
            "Certifications",
            products.map { listOf(it.certifications.joinToString(", ").ifEmpty { "—" }) },
        ),
    )
    // Group and spec order: first appearance across the products, as the backend sends them.
    val groups = linkedMapOf<String, String>()
    val specs = linkedMapOf<String, LinkedHashMap<String, String>>()
    products.forEach { p ->
        p.specGroups.forEach { g ->
            groups.putIfAbsent(g.key, g.title)
            val bucket = specs.getOrPut(g.key) { linkedMapOf() }
            g.specs.forEach { bucket.putIfAbsent(it.key, it.label) }
        }
    }
    groups.forEach { (groupKey, title) ->
        rows += TableRow.Section(title)
        specs[groupKey].orEmpty().forEach { (specKey, label) ->
            rows += TableRow.Values(label, products.map { valuesOf(it, groupKey, specKey) })
        }
    }
    return rows
}

private fun valuesOf(product: Product, groupKey: String, specKey: String): List<String> {
    val spec: Spec = product.specGroups.firstOrNull { it.key == groupKey }
        ?.specs?.firstOrNull { it.key == specKey } ?: return listOf("—")
    return spec.values.map(::formatSpecValue).ifEmpty { listOf("—") }
}
