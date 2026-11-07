package io.github.santiesc06.series76.ui.chat

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.santiesc06.series76.ui.common.ErrorState
import io.github.santiesc06.series76.ui.common.LoadingState

/** Example questions shown in an empty chat; tapping one sends it. */
private val EXAMPLES = listOf(
    "What is the torque of 763B00-11300000/A?",
    "Explosionproof, 220V single phase, modulating, at least 2000 Nm",
    "Compare 762A00-11300000/A and 762B00-11300000/A",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    onBack: () -> Unit,
    onOpenDebug: ((messageId: String) -> Unit)?,
    viewModel: ChatViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var input by rememberSaveable { mutableStateOf("") }
    val listState = rememberLazyListState()

    // Keep the newest message (or the typing indicator) in view.
    LaunchedEffect(state.items.size, state.sending) {
        val last = state.items.size + if (state.sending) 1 else 0
        if (last > 0) listState.animateScrollToItem(last - 1)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        state.title ?: "New conversation",
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
        bottomBar = {
            InputBar(
                value = input,
                onValueChange = { input = it.take(MAX_QUERY_LENGTH) },
                enabled = !state.sending && !state.loadingHistory && state.historyError == null,
                onSend = {
                    viewModel.send(input)
                    input = ""
                },
            )
        },
    ) { padding ->
        val modifier = Modifier.padding(padding).fillMaxSize()
        when {
            state.loadingHistory -> LoadingState(modifier, "Loading conversation…")
            state.historyError != null ->
                ErrorState(state.historyError!!.message, viewModel::loadHistory, modifier)
            state.items.isEmpty() && !state.sending -> EmptyChat(onExample = viewModel::send, modifier)
            else -> LazyColumn(
                state = listState,
                modifier = modifier,
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                val lastAssistantId = state.items.lastOrNull { it is ChatItem.Assistant }?.id
                items(state.items, key = { it.id }) { item ->
                    when (item) {
                        is ChatItem.User -> UserMessage(
                            item,
                            errorMessage = state.sendError?.message,
                            onRetry = { viewModel.retry(item) },
                        )
                        is ChatItem.Assistant -> AssistantMessage(
                            item,
                            // Quick replies only make sense on the latest answer (US-18 AC4).
                            showQuickReplies = item.id == lastAssistantId &&
                                item == state.items.last() && !state.sending,
                            onQuickReply = viewModel::send,
                            onOpenDebug = onOpenDebug,
                        )
                    }
                }
                if (state.sending) item(key = "typing") { TypingIndicator() }
            }
        }
    }
}

@Composable
private fun UserMessage(item: ChatItem.User, errorMessage: String?, onRetry: () -> Unit) {
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
        Surface(
            color = MaterialTheme.colorScheme.primaryContainer,
            shape = RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp),
            modifier = Modifier.widthIn(max = 320.dp),
        ) {
            Text(item.text, Modifier.padding(12.dp), style = MaterialTheme.typography.bodyLarge)
        }
        if (item.failed) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Filled.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(16.dp),
                )
                Text(
                    " Not sent. ${errorMessage ?: ""}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.widthIn(max = 240.dp),
                )
                TextButton(onClick = onRetry) {
                    Icon(Icons.Filled.Refresh, contentDescription = null, Modifier.size(16.dp))
                    Text(" Retry")
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
private fun AssistantMessage(
    item: ChatItem.Assistant,
    showQuickReplies: Boolean,
    onQuickReply: (String) -> Unit,
    onOpenDebug: ((String) -> Unit)?,
) {
    var menuOpen by remember { mutableStateOf(false) }
    var compare by rememberSaveable(item.id) { mutableStateOf(item.view == "comparison") }

    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Box {
            Surface(
                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                shape = RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp),
                modifier = Modifier
                    .widthIn(max = 340.dp)
                    // Hidden developer entry (design M5): long-press, debug builds only.
                    .combinedClickable(
                        onClick = {},
                        onLongClick = if (onOpenDebug != null) {
                            { menuOpen = true }
                        } else {
                            null
                        },
                    ),
            ) {
                Text(item.text, Modifier.padding(12.dp), style = MaterialTheme.typography.bodyLarge)
            }
            if (onOpenDebug != null) {
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    DropdownMenuItem(
                        text = { Text("Developer details") },
                        onClick = {
                            menuOpen = false
                            onOpenDebug(item.id)
                        },
                    )
                }
            }
        }

        if (item.products.size >= 2) {
            TextButton(onClick = { compare = !compare }) {
                Text(if (compare) "Show as cards" else "Compare side by side")
            }
        }
        if (compare && item.products.size >= 2) {
            ComparisonTable(item.products)
        } else {
            item.products.forEach { ProductCard(it) }
        }

        if (item.alternatives.isNotEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Info, contentDescription = null, Modifier.size(18.dp))
                Text(
                    "  Closest alternatives (not full matches)",
                    style = MaterialTheme.typography.titleSmall,
                )
            }
            item.alternatives.forEach { ProductCard(it) }
        }

        if (showQuickReplies && item.quickReplies.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                item.quickReplies.forEach { reply ->
                    SuggestionChip(
                        onClick = { onQuickReply(reply.message) },
                        label = { Text(reply.label) },
                    )
                }
            }
        }
    }
}

/** Shown while the agent answers (US-18 AC3): one request per turn, no streaming (C3). */
@Composable
private fun TypingIndicator() {
    val transition = rememberInfiniteTransition(label = "typing")
    Row(verticalAlignment = Alignment.CenterVertically) {
        Surface(
            color = MaterialTheme.colorScheme.surfaceContainerHigh,
            shape = RoundedCornerShape(16.dp),
        ) {
            Row(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
                repeat(3) { index ->
                    val alpha by transition.animateFloat(
                        initialValue = 0.25f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(
                            tween(durationMillis = 500, delayMillis = index * 150),
                            RepeatMode.Reverse,
                        ),
                        label = "dot$index",
                    )
                    Box(
                        Modifier
                            .padding(horizontal = 3.dp)
                            .size(8.dp)
                            .alpha(alpha)
                            .background(MaterialTheme.colorScheme.onSurfaceVariant, CircleShape),
                    )
                }
            }
        }
        Text(
            "  Checking the catalog…",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EmptyChat(onExample: (String) -> Unit, modifier: Modifier) {
    Column(
        modifier.padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Ask about a Series 76 actuator", style = MaterialTheme.typography.titleMedium)
        Spacer(Modifier.size(4.dp))
        Text(
            "Give a Base Part Number or describe your requirements.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.size(16.dp))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            EXAMPLES.forEach { example ->
                SuggestionChip(onClick = { onExample(example) }, label = { Text(example) })
            }
        }
    }
}

@Composable
private fun InputBar(
    value: String,
    onValueChange: (String) -> Unit,
    enabled: Boolean,
    onSend: () -> Unit,
) {
    val canSend = enabled && value.isNotBlank()
    Surface(tonalElevation = 3.dp, modifier = Modifier.navigationBarsPadding().imePadding()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = value,
                onValueChange = onValueChange,
                enabled = enabled,
                placeholder = { Text("Ask about an actuator…") },
                maxLines = 4,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { if (canSend) onSend() }),
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onSend, enabled = canSend) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = "Send")
            }
        }
    }
}
