def calculate_trades(df):
    results = []
    position_start_idx = None
    ongoing_offers = []
    already_transacted_pnl = [0, 0]  # [futures_pnl, spot_pnl]
    already_transacted_pnl_status = ["unfilled", "unfilled"]  # [futures_pnl, spot_pnl] # We will have partial or full
    entry_position_fut = 0 # This represents orders that we have yet to complete (futures)
    entry_position_spot = 0 # This represents orders that we have yet to complete (spot)
    funding_fee = 0
    borrowing_fee = 0
    
    for i in range(len(df)):
        row = df.iloc[i]
        
        # New position opened
        if position_start_idx is None and row['Position'] > 0:
            position_start_idx = i
            entry_row = df.iloc[position_start_idx]
            entry_position_fut = entry_row['Position']
            entry_position_spot = entry_row['Position']
        
        # Have active position and maker orders
        elif position_start_idx is not None:
            entry_row = df.iloc[position_start_idx]
            # entry_position = entry_row['Position']
            
            # Check if we should place maker orders
            exit_condition = (
                (entry_row['Identification'] == 'short' and row['basis'] < row['basis_entry_short_close']) or
                (entry_row['Identification'] == 'long' and row['basis'] > row['basis_entry_long_close'])
            )
            
            # Place new maker orders if we hit exit condition and don't have active orders
            if exit_condition and len(ongoing_offers) == 0:
                # Calculate desired exit prices (mid price as target)
                fut_exit_price = (row['askPx_x'] + row['bidPx_x']) / 2
                spot_exit_price = (row['askPx_y'] + row['bidPx_y']) / 2
                ongoing_offers = [fut_exit_price, spot_exit_price]
            
            if len(ongoing_offers) > 0:
                fut_target = ongoing_offers[0]
                spot_target = ongoing_offers[1]

                ### NOW I HAVE TO ADD IN THE LOGIC WHERE I SEE IF I AM ABLE TO CLEAR MY POSITION
                if entry_row['Identification'] == 'short':
                    # For short position:
                    # Futures: Need to buy back (check if someone hit our bid)
                    # Spot: Need to sell (check if someone lifted our ask)
                    if already_transacted_pnl_status[0] != "filled":
                        if row['askPx_x'] <= fut_target:
                            size_filled = min(row['askSz_x'], entry_position_fut)
                            already_transacted_pnl[0] += (entry_row['askPx_x'] - fut_target) * size_filled
                            if size_filled >= entry_position_fut:
                                ## This means we are fully filled up
                                already_transacted_pnl_status[0] = "filled"
                                entry_position_fut = 0
                            else:
                                already_transacted_pnl_status[0] = "partial"
                                entry_position_fut = entry_position_fut - size_filled

                            ### APPLY FUNDING FEE COMPUTATION
                            funding_fee += get_funding_fee(df.index[position_start_idx], df.index[i], entry_row['Identification'], size_filled)
                            
                    if already_transacted_pnl_status[1] != "filled":
                        if row['bidPx_y'] >= spot_target:
                            size_filled = min(row['bidSz_y'], entry_position_spot)
                            already_transacted_pnl[1] += (spot_target - entry_row['bidPx_y']) * size_filled
                            if size_filled >= entry_position_spot:
                                already_transacted_pnl_status[1] = "filled"
                                entry_position_spot = 0
                            else:
                                already_transacted_pnl_status[1] = "partial"
                                entry_position_spot = entry_position_spot - size_filled

                            ### APPLY BORROWING FEE COMPUTATION
                            borrowing_fee += get_borrowing_fee(df.index[position_start_idx], df.index[i], entry_row['Identification'], size_filled)
                            
                elif entry_row['Identification'] == 'long':
                    # For long position:
                    # Futures: Need to sell (check if someone lifted our ask)
                    # Spot: Need to buy back (check if someone hit our bid)
                    if already_transacted_pnl_status[0] != "filled":
                        if row['bidPx_x'] >= fut_target:
                            size_filled = min(row['bidSz_x'], entry_position_fut)
                            already_transacted_pnl[0] += (fut_target - entry_row['bidPx_x']) * size_filled
                            if size_filled >= entry_position_fut:
                                already_transacted_pnl_status[0] = "filled"
                                entry_position_fut = 0
                            else:
                                already_transacted_pnl_status[0] = "partial"
                                entry_position_fut = entry_position_fut - size_filled
                                
                            ### APPLY FEE COMPUTATION
                            funding_fee += get_funding_fee(df.index[position_start_idx], df.index[i], entry_row['Identification'], size_filled)
                
                    if already_transacted_pnl_status[1] != "filled":
                        if row['askPx_y'] <= spot_target:
                            size_filled = min(row['askSz_y'], entry_position_spot)
                            already_transacted_pnl[1] += (entry_row['askPx_y'] - spot_target) * size_filled
                            if size_filled >= entry_position_spot:
                                already_transacted_pnl_status[1] = "filled"
                                entry_position_spot = 0
                            else:
                                already_transacted_pnl_status[1] = "partial"
                                entry_position_spot = entry_position_spot - row['askSz_y']
                
                             ### APPLY FEE COMPUTATION
                            borrowing_fee += get_borrowing_fee(df.index[position_start_idx], df.index[i], entry_row['Identification'], size_filled)
            
                if already_transacted_pnl_status[0] == "filled" and already_transacted_pnl_status[1] == "filled":
                    total_pnl = (already_transacted_pnl[0] + already_transacted_pnl[1])
                    ## Adding fee assumption
                    ## Some fee information:
                    ### Taker 1.5BPS, Maker Swap -1 BPS, Maker Spot = -0.5BPS
                    ### So for Swap, we are paying 0.5BPS and for Spot, we are paying 1BPS
                    ### Therefore, in total, we are paying 1.5BPS
                    fees = entry_row['Position_Ntl'] * (1.5/10000) 
                                            
                    total_pnl_fees_adjusted = total_pnl - fees + funding_fee - borrowing_fee
                    
                    results.append({
                        'entry_time': df.index[position_start_idx],
                        'exit_time': df.index[i],
                        'position_type': entry_row['Identification'],
                        'entry_basis': entry_row['basis'],
                        'exit_basis': row['basis'],
                        'position_size': entry_row['Position'],  # Use the original position size
                        'position_ntl': entry_row['Position_Ntl'],
                        'futures_pnl': already_transacted_pnl[0],  # No need to multiply, size is included in calculation
                        'spot_pnl': already_transacted_pnl[1],     # No need to multiply, size is included in calculation
                        'funding_fee': funding_fee,
                        'borrow_fee': borrowing_fee,
                        'total_pnl': total_pnl_fees_adjusted,
                    })

                    
                    position_start_idx = None
                    ongoing_offers = []
                    already_transacted_pnl_status = ["unfilled", "unfilled"]
                    already_transacted_pnl = [0, 0]
                    entry_position_fut = 0
                    entry_position_spot = 0
                    funding_fee = 0
                    borrowing_fee = 0
    
    return pd.DataFrame(results)

trades_df = calculate_trades(merged_df)
trades_df['cumulative_pnl'] = trades_df['total_pnl'].cumsum()
