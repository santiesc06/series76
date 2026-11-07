package io.github.santiesc06.series76.devtools

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.santiesc06.series76.data.api.DebugInfo
import io.github.santiesc06.series76.data.api.DebugStep
import io.github.santiesc06.series76.ui.common.ErrorState
import io.github.santiesc06.series76.ui.common.LoadingState
import io.github.santiesc06.series76.ui.theme.CodeTextStyle
import io.github.santiesc06.series76.ui.theme.tabular
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import java.util.Locale

private val prettyJson = Json { prettyPrint = true }

private fun JsonElement?.pretty(): String =
    this?.let { prettyJson.encodeToString(JsonElement.serializer(), it) } ?: "—"

/** Developer screen (US-19 AC1): tool calls with arguments, raw results and durations. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DebugScreen(onBack: () -> Unit, viewModel: DebugViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Developer details") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        val modifier = Modifier.padding(padding).fillMaxSize()
        when (val s = state) {
            DebugUiState.Loading -> LoadingState(modifier)
            is DebugUiState.Error -> ErrorState(s.error.message, viewModel::load, modifier)
            is DebugUiState.Loaded -> DebugContent(s.info, modifier)
        }
    }
}

@Composable
private fun DebugContent(info: DebugInfo, modifier: Modifier) {
    LazyColumn(
        modifier = modifier,
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            OutlinedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Fact("Model", info.model ?: "—")
                    Fact("Latency", info.latencyMs?.let { "$it ms" } ?: "—")
                    Fact("Model calls", info.modelCalls?.toString() ?: "—")
                    Fact(
                        "Tokens",
                        info.tokens?.let { "${it.input} in / ${it.output} out" } ?: "—",
                    )
                    Fact(
                        "Estimated cost",
                        info.estimatedCostUsd?.let { String.format(Locale.US, "USD %.6f", it) } ?: "—",
                    )
                    Fact("Number check", info.numberCheck.pretty().replace("\n", " "))
                    if (info.rejectedRefs.isNotEmpty()) {
                        Fact("Rejected part numbers", info.rejectedRefs.joinToString())
                    }
                    info.slotFix?.let { Fact("Slot fix", it) }
                }
            }
        }
        info.contextNote?.let { note ->
            item {
                Section("Conversation context sent to the model")
                Code(note)
            }
        }
        item { Section("Tool calls (${info.steps.size})") }
        itemsIndexed(info.steps) { index, step -> StepCard(index + 1, step) }
    }
}

@Composable
private fun StepCard(number: Int, step: DebugStep) {
    var expanded by rememberSaveable { mutableStateOf(number == 1) }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                Modifier.fillMaxWidth().clickable { expanded = !expanded },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "$number. ${step.tool}",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    step.durationMs?.let { "$it ms" } ?: "",
                    style = MaterialTheme.typography.bodySmall.tabular(),
                )
                Icon(
                    if (expanded) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
                    contentDescription = if (expanded) "Collapse" else "Expand",
                )
            }
            step.error?.let {
                Text("Error: $it", color = MaterialTheme.colorScheme.error)
            }
            if (expanded) {
                Text("Arguments", style = MaterialTheme.typography.labelLarge)
                Code(step.args.pretty())
                Text("Result", style = MaterialTheme.typography.labelLarge)
                Code(step.result.pretty())
            }
        }
    }
}

@Composable
private fun Fact(label: String, value: String) {
    Row {
        Text(
            label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.weight(0.4f),
        )
        Text(value, style = MaterialTheme.typography.bodyMedium.tabular(), modifier = Modifier.weight(0.6f))
    }
}

@Composable
private fun Section(title: String) {
    Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
}

@Composable
private fun Code(text: String) {
    SelectionContainer {
        Text(
            text,
            style = CodeTextStyle.merge(MaterialTheme.typography.bodySmall),
            modifier = Modifier.horizontalScroll(rememberScrollState()),
        )
    }
}
